import argparse
import io
import logging
import sys
from collections.abc import Callable, Sequence
from importlib import resources
from pathlib import Path

from a_jobseeker import __version__
from a_jobseeker.ai import AI_BACKENDS, create_backend
from a_jobseeker.config import Config, Profile
from a_jobseeker.errors import JobseekerError
from a_jobseeker.filters import OfferFilter
from a_jobseeker.outputs import OUTPUTS, create_output
from a_jobseeker.paths import AppDirs
from a_jobseeker.pipeline import (
    JOBS_ADAPTER,
    Pipeline,
    RunOptions,
    build_scrapers,
    collect_jobs,
    create_cache,
    load_application,
    render_match,
)
from a_jobseeker.scrapers import SCRAPERS
from a_jobseeker.templates import CV_TEMPLATES, LETTER_TEMPLATES

log = logging.getLogger("a_jobseeker")

Command = Callable[[argparse.Namespace], int]

EXIT_OK = 0
EXIT_PARTIAL_FAILURE = 1
EXIT_ERROR = 2
EXIT_INTERRUPTED = 130

LOG_FORMAT = "%(levelname)s %(message)s"


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command line interface and return the exit code."""
    args = build_parser().parse_args(argv)
    # basicConfig() only attaches the console handler once per process (harmless
    # in production, where main() runs once); the level is reapplied every time so
    # that repeated calls (e.g. in tests) still honor their own -v/-vv.
    logging.basicConfig(format=LOG_FORMAT, stream=sys.stderr)
    logging.getLogger().setLevel(
        [logging.WARNING, logging.INFO, logging.DEBUG][min(args.verbose, 2)]
    )
    if args.verbose < 2:
        logging.getLogger("urllib3").setLevel(logging.WARNING)
    command: Command = args.command
    try:
        return command(args)
    except JobseekerError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_ERROR
    except KeyboardInterrupt:
        return EXIT_INTERRUPTED


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #


def app_dirs(args: argparse.Namespace) -> AppDirs:
    """Resolve the directories from the command line options."""
    return AppDirs.resolve(
        config=args.config_dir, data=args.data_dir, cache=args.cache_dir
    )


def cmd_init(args: argparse.Namespace) -> int:
    """Write example profile and config files in the configuration directory."""
    dirs = app_dirs(args)
    dirs.config.mkdir(parents=True, exist_ok=True)
    examples = resources.files("a_jobseeker").joinpath("resources")
    for target in (dirs.profile_file, dirs.config_file):
        if target.exists() and not args.force:
            print(
                f"{target} already exists (use --force to overwrite)", file=sys.stderr
            )
            continue
        text = examples.joinpath(target.name).read_text(encoding="utf-8")
        target.write_text(text, encoding="utf-8")
        print(f"created: {target}")
    return EXIT_OK


def cmd_dirs(args: argparse.Namespace) -> int:
    """Print the directories used by the program."""
    dirs = app_dirs(args)
    print(f"config: {dirs.config}\ndata:   {dirs.data}\ncache:  {dirs.cache}")
    return EXIT_OK


def cmd_run(args: argparse.Namespace) -> int:
    """Run the whole pipeline, capturing its logs for outputs that attach them."""
    log_buffer = io.StringIO()
    capture = logging.StreamHandler(log_buffer)
    capture.setFormatter(logging.Formatter(LOG_FORMAT))
    root_logger = logging.getLogger()
    root_logger.addHandler(capture)
    try:
        dirs = app_dirs(args)
        config = Config.load(dirs.config_file)
        overrides = {
            "provider": args.ai or config.ai.provider,
            "path": args.ai_path or config.ai.path,
        }
        config = config.model_copy(
            update={"ai": config.ai.model_copy(update=overrides)}
        )
        profile = Profile.load(dirs.profile_file)

        output_config = config.output.model_copy(
            update={"type": args.output or config.output.type}
        )
        pipeline = Pipeline(
            config,
            profile,
            create_backend(config.ai),
            create_output(output_config, profile),
            dirs,
        )
        report = pipeline.run(
            RunOptions(
                jobs_file=args.jobs_file,
                limit=args.limit,
                ignore_seen=args.ignore_seen,
            ),
            log_buffer,
        )
    finally:
        root_logger.removeHandler(capture)
    if report.failed_batches:
        print(
            f"warning: {report.failed_batches} batch(es) could not be evaluated",
            file=sys.stderr,
        )
        return EXIT_PARTIAL_FAILURE
    return EXIT_OK


def cmd_scrape(args: argparse.Namespace) -> int:
    """Collect offers without calling the AI and write them as JSON."""
    dirs = app_dirs(args)
    config = Config.load(dirs.config_file)
    profile = Profile.load(dirs.profile_file)
    offer_filter = OfferFilter(profile)
    jobs = collect_jobs(
        config, build_scrapers(config, create_cache(config, dirs)), offer_filter.rejects
    )
    output = JOBS_ADAPTER.dump_json(jobs, indent=2).decode() + "\n"
    if args.output:
        args.output.write_text(output, encoding="utf-8")
        print(f"{len(jobs)} offer(s) saved to {args.output}", file=sys.stderr)
    else:
        sys.stdout.write(output)
    return EXIT_OK


def cmd_render(args: argparse.Namespace) -> int:
    """Render the documents again from edited ``application.json`` files."""
    profile = Profile.load(app_dirs(args).profile_file)
    for path in args.applications:
        match, cv, letter = load_application(path)
        render_match(match, profile, cv, letter, path.parent)
        print(f"{match.cv_path}\n{match.letter_path}")
    return EXIT_OK


def cmd_list(_: argparse.Namespace) -> int:
    """List the available extension implementations."""
    sections: list[tuple[str, list[tuple[str, str]]]] = [
        ("Sources", [(cls.name, "") for cls in SCRAPERS]),
        (
            "AI providers",
            [(cls.name, f"default path: {cls.default_path}") for cls in AI_BACKENDS],
        ),
        ("Outputs", [(cls.name, cls.description) for cls in OUTPUTS]),
        ("CV templates", [(cls.name, cls.description) for cls in CV_TEMPLATES]),
        (
            "Cover letter templates",
            [(cls.name, cls.description) for cls in LETTER_TEMPLATES],
        ),
    ]
    for title, items in sections:
        print(f"{title}:")
        for name, description in items:
            print(f"  {name:12} {description}".rstrip())
    return EXIT_OK


# --------------------------------------------------------------------------- #
# Parser
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    """Build the command line parser."""
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "-v", "--verbose", action="count", default=0, help="-v: progress, -vv: debug"
    )
    common.add_argument(
        "--config-dir",
        type=Path,
        metavar="DIR",
        help="directory of config.json and profile.json "
        "(default: ~/.config/a-jobseeker)",
    )
    common.add_argument(
        "--data-dir",
        type=Path,
        metavar="DIR",
        help="directory of the generated applications and run history "
        "(default: ~/.local/share/a-jobseeker)",
    )
    common.add_argument(
        "--cache-dir",
        type=Path,
        metavar="DIR",
        help="directory of the cached offers (default: ~/.cache/a-jobseeker)",
    )

    parser = argparse.ArgumentParser(
        prog="a-jobseeker",
        description="Scrape job offers, select the ones matching your profile with "
        "an AI and generate a tailored CV and cover letter for each.",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    sub = parser.add_subparsers(required=True, metavar="COMMAND")

    def add_command(
        name: str, command: Command, help_text: str
    ) -> argparse.ArgumentParser:
        p = sub.add_parser(
            name, parents=[common], help=help_text, description=help_text
        )
        p.set_defaults(command=command)
        return p

    p = add_command(
        "init", cmd_init, "write example config.json and profile.json files"
    )
    p.add_argument("--force", action="store_true", help="overwrite existing files")

    p = add_command(
        "run", cmd_run, "collect and select offers, then generate the applications"
    )
    p.add_argument(
        "-o",
        "--output",
        choices=OUTPUTS.names(),
        help="how results are published (default: stdout)",
    )
    p.add_argument(
        "--ai", choices=AI_BACKENDS.names(), help="AI provider (default: claude)"
    )
    p.add_argument("--ai-path", help="path of the AI command line program")
    p.add_argument(
        "--jobs-file",
        type=Path,
        help="use offers saved by 'scrape' instead of scraping",
    )
    p.add_argument("--limit", type=int, help="maximum number of offers sent to the AI")
    p.add_argument(
        "--ignore-seen",
        action="store_true",
        help="evaluate again offers seen in previous runs",
    )

    p = add_command(
        "scrape", cmd_scrape, "collect offers as JSON, without calling the AI"
    )
    p.add_argument("-o", "--output", type=Path, help="output file (default: stdout)")

    p = add_command(
        "render", cmd_render, "render the documents again from application.json files"
    )
    p.add_argument(
        "applications", nargs="+", type=Path, help="application.json file(s)"
    )

    add_command("dirs", cmd_dirs, "print the configuration, data and cache directories")
    add_command("list", cmd_list, "list sources, AI providers, outputs and templates")

    return parser
