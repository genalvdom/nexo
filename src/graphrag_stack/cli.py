"""Command line entry point: ingest, ask, review, status, eval."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from graphrag_stack.config import get_settings
from graphrag_stack.telemetry import shutdown_telemetry


def _print(model) -> None:
    print(model.model_dump_json(indent=2, exclude_none=True))


def _ingest(args: argparse.Namespace) -> int:
    from graphrag_stack.service import open_ingestor
    from graphrag_stack.storage.schemas import DocumentMetadata, Sensitivity

    metadata = DocumentMetadata(
        source_id=args.source_id or Path(args.file).stem,
        title=args.title or Path(args.file).stem,
        doc_type=args.doc_type,
        source_uri=args.source_uri or Path(args.file).resolve().as_uri(),
        effective_date=date.fromisoformat(args.effective_date) if args.effective_date else None,
        sensitivity=Sensitivity(args.sensitivity),
    )
    with open_ingestor(get_settings()) as ingestor:
        report = ingestor.ingest(Path(args.file).read_text(encoding="utf-8"), metadata)
    _print(report)
    return 1 if report.failed_chunk_ids else 0


def _ask(args: argparse.Namespace) -> int:
    from graphrag_stack.service import open_runtime

    with open_runtime(get_settings()) as runtime:
        _print(runtime.start(args.query, thread_id=args.thread_id, clearance=args.clearance))
    return 0


def _review(args: argparse.Namespace) -> int:
    from graphrag_stack.service import open_runtime

    decision = {
        "approval_status": "approved" if args.approve else "rejected",
        "reviewer": args.reviewer,
        "comment": args.comment,
        "acknowledged_findings": args.acknowledge_findings,
    }
    with open_runtime(get_settings()) as runtime:
        _print(runtime.review(args.thread_id, decision))
    return 0


def _status(args: argparse.Namespace) -> int:
    from graphrag_stack.service import open_runtime

    with open_runtime(get_settings()) as runtime:
        _print(runtime.status(args.thread_id))
    return 0


def _eval(args: argparse.Namespace) -> int:
    """Each JSONL line: {"question", "relevant_chunk_ids": [...], "reference_answer"?}."""
    from langchain_openai import ChatOpenAI

    from graphrag_stack.agents.investigator import Investigator
    from graphrag_stack.evaluation import judge_faithfulness, judge_relevancy, record_metrics, retrieval_scores
    from graphrag_stack.llm import build_embeddings, build_strands_model
    from graphrag_stack.storage.graph_store import GraphStore
    from graphrag_stack.storage.vector_store import LocalChunkStore
    from graphrag_stack.telemetry import setup_telemetry, traced_span

    settings = get_settings()
    setup_telemetry(settings)
    judge = None
    if settings.judge_model:
        judge = ChatOpenAI(base_url=settings.judge_base_url or settings.vllm_base_url, model=settings.judge_model,
                           api_key=settings.vllm_api_key, temperature=0)
    graph = GraphStore.from_settings(settings, read_only=True)
    chunks = LocalChunkStore(build_embeddings(settings), settings.vector_store_path)
    investigator = Investigator(model=build_strands_model(settings), graph=graph, chunks=chunks,
                                settings=settings, schema_text=graph.describe_schema())
    try:
        for line in Path(args.dataset).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            case = json.loads(line)
            with traced_span("eval.case"):
                output = investigator.investigate(case["question"])
                metrics = retrieval_scores(output, case.get("relevant_chunk_ids", []))
                if judge and output.answer:
                    evidence = [c.text for c in chunks.get_by_ids(output.citations)]
                    metrics["generation.faithfulness"] = judge_faithfulness(judge, output.answer, evidence).score
                    metrics["generation.relevancy"] = judge_relevancy(judge, case["question"], output.answer).score
                record_metrics(metrics)
            print(json.dumps({"question": case["question"], **metrics}))
    finally:
        graph.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="graphrag")
    sub = parser.add_subparsers(dest="command", required=True)

    ingest = sub.add_parser("ingest", help="chunk, embed and extract a text/Markdown document")
    ingest.add_argument("file")
    ingest.add_argument("--source-id")
    ingest.add_argument("--title")
    ingest.add_argument("--doc-type", default="general")
    ingest.add_argument("--source-uri")
    ingest.add_argument("--effective-date", help="YYYY-MM-DD")
    ingest.add_argument("--sensitivity", default="internal", choices=["public", "internal", "pii", "phi"])
    ingest.set_defaults(handler=_ingest)

    ask = sub.add_parser("ask", help="start an investigation (pauses for review)")
    ask.add_argument("query")
    ask.add_argument("--thread-id")
    ask.add_argument("--clearance", choices=["public", "internal", "pii", "phi"])
    ask.set_defaults(handler=_ask)

    review = sub.add_parser("review", help="approve or reject a paused investigation")
    review.add_argument("thread_id")
    verdict = review.add_mutually_exclusive_group(required=True)
    verdict.add_argument("--approve", action="store_true")
    verdict.add_argument("--reject", action="store_true")
    review.add_argument("--reviewer", required=True)
    review.add_argument("--comment")
    review.add_argument("--acknowledge-findings", action="store_true")
    review.set_defaults(handler=_review)

    status = sub.add_parser("status", help="show a thread's state")
    status.add_argument("thread_id")
    status.set_defaults(handler=_status)

    evaluate = sub.add_parser("eval", help="run the investigator over a JSONL golden set")
    evaluate.add_argument("dataset")
    evaluate.set_defaults(handler=_eval)

    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    finally:
        shutdown_telemetry()


if __name__ == "__main__":
    sys.exit(main())
