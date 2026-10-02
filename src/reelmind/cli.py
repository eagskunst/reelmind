"""typer + rich CLI. All progress/UI lives here; core modules stay quiet."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.table import Table

from reelmind.ask import ask as run_ask
from reelmind.config import DEFAULT_CONFIG_TOML, Config, load_config
from reelmind.importers import import_path
from reelmind.llm import OpenAICompatClient
from reelmind.models import VideoRef
from reelmind.pipeline.processor import Processor
from reelmind.pipeline.transcribe import build_transcriber
from reelmind.platforms import all_platforms, default_registry
from reelmind.storage import Storage

app = typer.Typer(help="reelmind — ask questions about your saved videos.", no_args_is_help=True)
console = Console()
err = Console(stderr=True)


def _load(config_path: Path | None) -> Config:
    try:
        return load_config(config_path)
    except Exception as e:
        err.print(f"[red]Failed to load config: {e}[/red]")
        raise typer.Exit(2) from e


def _processor(cfg: Config) -> tuple[Storage, Processor]:
    storage = Storage(cfg.db_path)
    llm = OpenAICompatClient(cfg.llm)
    return storage, Processor(cfg, storage, llm, build_transcriber(cfg))


ConfigOpt = Annotated[
    Path | None, typer.Option("--config", help="Path to a reelmind TOML config file.")
]


@app.command()
def init(config: ConfigOpt = None) -> None:
    """Write a commented default config file."""
    path = config or (Path.cwd() / "reelmind.toml")
    if path.exists():
        err.print(f"[yellow]{path} already exists[/yellow]")
        raise typer.Exit(1)
    path.write_text(DEFAULT_CONFIG_TOML)
    console.print(f"[green]Wrote {path}[/green]")
    console.print(
        "Set your API key env var (e.g. GEMINI_API_KEY) and you're ready: reelmind add <url>"
    )


def _resolve_urls(urls: list[str], cfg: Config) -> tuple[list[VideoRef], int]:
    """Parse URLs; expand list/collection URLs via the owning platform."""
    refs: list[VideoRef] = []
    expanded = 0
    for url in urls:
        platform = default_registry.for_url(url)
        if platform is None:
            err.print(f"[yellow]Skipping unsupported URL: {url}[/yellow]")
            continue
        ref = platform.parse(url)
        if ref is not None:
            refs.append(ref)
            continue
        console.print(f"Expanding list URL: {url}")
        try:
            expanded_refs = platform.expand(url, cfg)
        except Exception as e:  # noqa: BLE001
            err.print(f"[red]Failed to expand {url}: {e}[/red]")
            continue
        expanded += len(expanded_refs)
        refs.extend(expanded_refs)
    # dedupe
    seen: set[tuple[str, str]] = set()
    unique = []
    for r in refs:
        if (r.platform, r.video_id) not in seen:
            seen.add((r.platform, r.video_id))
            unique.append(r)
    return unique, expanded


@app.command()
def add(
    urls: Annotated[list[str], typer.Argument(help="Video or list/collection URLs.")] = [],  # noqa: B006 — typer uses the default as the empty case
    file: Annotated[Path | None, typer.Option("--file", "-f", help="Text file with URLs.")] = None,
    no_process: Annotated[bool, typer.Option("--no-process", help="Only enqueue.")] = False,
    config: ConfigOpt = None,
) -> None:
    """Add videos (or whole lists/collections) by URL."""
    cfg = _load(config)
    all_urls = list(urls)
    if file:
        all_urls += [line.strip() for line in file.read_text().splitlines() if line.strip()]
    if not all_urls:
        err.print("[red]No URLs given.[/red]")
        raise typer.Exit(1)
    refs, expanded = _resolve_urls(all_urls, cfg)
    storage, processor = _processor(cfg)
    new = processor.enqueue(refs)
    console.print(
        f"[green]Enqueued {new} new video(s)[/green] ({len(refs)} refs, {expanded} from lists)"
    )
    if not no_process and new:
        _run_processing(processor)


@app.command(name="import")
def import_cmd(
    path: Annotated[Path, typer.Argument(help="Export file/dir/zip (TikTok or Instagram).")],
    limit: Annotated[int | None, typer.Option("--limit")] = None,
    no_process: Annotated[bool, typer.Option("--no-process")] = False,
    config: ConfigOpt = None,
) -> None:
    """Import a saved-videos export (format-agnostic URL extraction)."""
    cfg = _load(config)
    if not path.exists():
        err.print(f"[red]Not found: {path}[/red]")
        raise typer.Exit(1)
    refs, unsupported = import_path(path)
    if limit is not None:
        refs = refs[:limit]
    console.print(
        f"Found [bold]{len(refs)}[/bold] supported video(s); "
        f"{len(unsupported)} unsupported URL(s) ignored."
    )
    storage, processor = _processor(cfg)
    new = processor.enqueue(refs)
    console.print(f"[green]Enqueued {new} new video(s)[/green]")
    if not no_process and new:
        _run_processing(processor)


def _run_processing(
    processor: Processor, retry_failed: bool = False, limit: int | None = None
) -> None:
    def on_event(event: str, info: dict[str, Any]) -> None:
        if event == "done":
            console.print(f"  [green]done[/green] {info['url']}")
        elif event == "failed":
            console.print(f"  [red]failed[/red] {info['url']} — {info.get('error', '')}")

    counts = processor.process_pending(retry_failed=retry_failed, limit=limit, on_event=on_event)
    console.print(
        f"[bold]Finished:[/bold] {counts['done']} done, {counts['failed']} failed, "
        f"{counts['skipped']} skipped"
    )


@app.command()
def process(
    retry_failed: Annotated[bool, typer.Option("--retry-failed")] = False,
    limit: Annotated[int | None, typer.Option("--limit")] = None,
    config: ConfigOpt = None,
) -> None:
    """Process the pending queue."""
    cfg = _load(config)
    _, processor = _processor(cfg)
    _run_processing(processor, retry_failed=retry_failed, limit=limit)


@app.command(name="list")
def list_cmd(
    category: Annotated[str | None, typer.Option("--category")] = None,
    city: Annotated[str | None, typer.Option("--city")] = None,
    upcoming: Annotated[bool, typer.Option("--upcoming")] = False,
    search: Annotated[str | None, typer.Option("--search", help="Full-text search terms.")] = None,
    all_statuses: Annotated[bool, typer.Option("--all", help="Include pending/failed.")] = False,
    config: ConfigOpt = None,
) -> None:
    """List saved videos."""
    cfg = _load(config)
    storage = Storage(cfg.db_path)
    rows = storage.search(
        categories=[category] if category else None,
        city=city,
        upcoming_only=upcoming,
        keywords=[search] if search else None,
        limit=200,
        done_only=not all_statuses,
    )
    table = Table("id", "cat", "title", "places/events", "url")
    for v in rows:
        pe = ", ".join(
            [p["name"] for p in v["places"] if p["name"]]
            + [e["name"] for e in v["events"] if e["name"]]
        )
        table.add_row(str(v["id"]), v["category"] or "", (v["title"] or "")[:50], pe[:60], v["url"])
    console.print(table)


@app.command()
def show(id: Annotated[int, typer.Argument()], config: ConfigOpt = None) -> None:
    """Show full details of one video."""
    cfg = _load(config)
    storage = Storage(cfg.db_path)
    v = storage.get(id)
    if v is None:
        err.print(f"[red]No video with id {id}[/red]")
        raise typer.Exit(1)
    console.print_json(json.dumps(v, default=str))


@app.command()
def ask(
    question: Annotated[str, typer.Argument()],
    config: ConfigOpt = None,
) -> None:
    """Ask a question about your saved videos."""
    cfg = _load(config)
    storage = Storage(cfg.db_path)
    llm = OpenAICompatClient(cfg.llm)
    result = run_ask(question, cfg, storage, llm)
    console.print(result.answer)


@app.command()
def serve(
    host: Annotated[str, typer.Option("--host")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port")] = 8765,
    config: ConfigOpt = None,
) -> None:
    """Run the local web UI."""
    import uvicorn

    from reelmind.web.app import create_app

    cfg = _load(config)
    storage = Storage(cfg.db_path)
    llm = OpenAICompatClient(cfg.llm)
    processor = Processor(cfg, storage, llm, build_transcriber(cfg))
    console.print(f"Serving on http://{host}:{port}")
    uvicorn.run(create_app(cfg, storage, processor, llm), host=host, port=port)


@app.command()
def platforms() -> None:
    """List registered platforms."""
    for p in all_platforms():
        console.print(f"- {p.name} ({type(p).__name__})")


@app.command()
def stats(config: ConfigOpt = None) -> None:
    """Counts per category/status + token usage per model."""
    cfg = _load(config)
    storage = Storage(cfg.db_path)
    counts = storage.counts()
    console.print("[bold]Status[/bold]", counts["by_status"])
    console.print("[bold]Category[/bold]", counts["by_category"])
    table = Table("model", "purpose", "prompt_tokens", "completion_tokens")
    for row in counts["usage"]:
        table.add_row(
            row["model"], row["purpose"], str(row["prompt_tokens"]), str(row["completion_tokens"])
        )
    console.print(table)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
