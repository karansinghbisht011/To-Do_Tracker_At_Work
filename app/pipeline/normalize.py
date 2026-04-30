from app.connectors.base import CandidateTask
from app.pipeline.extract import enrich_with_llm, enrich_trello_comments


async def normalize_events(source: str, events: list[dict], connector) -> list[CandidateTask]:
    """Convert raw events to CandidateTasks, enriching with LLM where needed."""
    candidates: list[CandidateTask] = []

    for event in events:
        tasks = connector.normalize(event)
        for task in tasks:
            if source in ("slack", "gmail"):
                task = await enrich_with_llm(task)
            elif source == "trello" and event.get("comments"):
                task = await enrich_trello_comments(task)
            candidates.append(task)

    return candidates
