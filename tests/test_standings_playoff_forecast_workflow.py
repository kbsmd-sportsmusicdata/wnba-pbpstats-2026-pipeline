"""Semantic contract tests for the manual standings forecast workflow."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = (
    REPOSITORY_ROOT / ".github/workflows/standings-playoff-forecast.yml"
)
REQUIRED_ARTIFACTS = (
    "analysis/standings_playoff_forecast/deliverables/season=2026/latest/wnba_standings_playoff_forecast.xlsx",
    "analysis/standings_playoff_forecast/deliverables/season=2026/latest/wnba_broadcast_forecast_brief.md",
    "analysis/standings_playoff_forecast/deliverables/season=2026/latest/wnba_playoff_stat_pack_insert.html",
    "analysis/standings_playoff_forecast/deliverables/season=2026/latest/dashboard/index.html",
    "analysis/standings_playoff_forecast/deliverables/season=2026/latest/dashboard/assets/styles.css",
    "analysis/standings_playoff_forecast/deliverables/season=2026/latest/dashboard/assets/app.js",
    "analysis/standings_playoff_forecast/deliverables/season=2026/latest/dashboard/assets/charts.js",
    "analysis/standings_playoff_forecast/deliverables/season=2026/latest/dashboard/data/forecast_payload.json",
    "analysis/standings_playoff_forecast/data/processed/season=2026/latest/run_manifest.json",
)


def _run(
    command: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        check=check,
        capture_output=True,
        text=True,
    )


def _load_workflow() -> dict[str, object]:
    ruby = shutil.which("ruby")
    if ruby is None:
        raise AssertionError("Ruby stdlib YAML parser is required for workflow tests")
    program = textwrap.dedent(
        """
        require "yaml"
        require "json"
        document = YAML.safe_load(File.read(ARGV.fetch(0)), aliases: true)
        puts JSON.generate(document)
        """
    )
    result = _run([ruby, "-e", program, str(WORKFLOW_PATH)])
    return json.loads(result.stdout)


def _steps(workflow: dict[str, object]) -> list[dict[str, object]]:
    jobs = workflow["jobs"]
    assert isinstance(jobs, dict)
    job = jobs["standings-playoff-forecast"]
    assert isinstance(job, dict)
    steps = job["steps"]
    assert isinstance(steps, list)
    return steps


def _named_step(
    workflow: dict[str, object], name: str
) -> dict[str, object]:
    for step in _steps(workflow):
        if step.get("name") == name:
            return step
    raise AssertionError(f"workflow step not found: {name}")


def _workflow_env(**overrides: str) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "FORECAST_SEASON": "2026",
            "FORECAST_CUTOFF": "",
            "FORECAST_SIMULATIONS": "100000",
            "REFRESH_SPORTSDATAVERSE": "false",
            "REFRESH_PBPSTATS": "false",
        }
    )
    env["PATH"] = f"{Path(sys.executable).parent}:{env['PATH']}"
    env.update(overrides)
    return env


class WorkflowContractTests(unittest.TestCase):
    def test_dispatch_contract_and_runner_setup_are_exact(self) -> None:
        workflow = _load_workflow()
        dispatch = workflow["on"]["workflow_dispatch"]  # type: ignore[index]
        inputs = dispatch["inputs"]

        expected = {
            "season": ("string", True, "2026"),
            "cutoff": ("string", False, ""),
            "simulations": ("string", True, "100000"),
            "refresh_sportsdataverse": ("boolean", True, False),
            "refresh_pbpstats": ("boolean", True, False),
            "run_tests": ("boolean", True, True),
            "commit_outputs": ("boolean", True, False),
        }
        self.assertEqual(set(inputs), set(expected))
        for input_name, (input_type, required, default) in expected.items():
            definition = inputs[input_name]
            self.assertEqual(definition["type"], input_type)
            self.assertIs(definition["required"], required)
            self.assertEqual(definition["default"], default)

        job = workflow["jobs"]["standings-playoff-forecast"]  # type: ignore[index]
        self.assertEqual(job["runs-on"], "ubuntu-latest")
        self.assertEqual(job["permissions"], {"contents": "write"})
        self.assertGreaterEqual(job["timeout-minutes"], 30)
        self.assertFalse(workflow["concurrency"]["cancel-in-progress"])  # type: ignore[index]

        steps = _steps(workflow)
        checkout = next(step for step in steps if step.get("uses") == "actions/checkout@v7")
        setup = next(step for step in steps if step.get("uses") == "actions/setup-python@v7")
        self.assertEqual(setup["with"]["python-version"], "3.11")
        self.assertIsInstance(checkout, dict)
        install = _named_step(workflow, "Install dependencies")["run"]
        self.assertIn("python -m pip install --upgrade pip", install)
        self.assertIn("pip install -r requirements.txt", install)

    def test_workflow_parses_and_every_shell_block_passes_bash_syntax(self) -> None:
        workflow = _load_workflow()
        run_blocks = [step["run"] for step in _steps(workflow) if "run" in step]
        self.assertGreaterEqual(len(run_blocks), 7)
        for block in run_blocks:
            result = subprocess.run(
                ["bash", "-n", "-"],
                input=block,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_validation_accepts_valid_values_and_rejects_unsafe_inputs(self) -> None:
        workflow = _load_workflow()
        validation = _named_step(workflow, "Validate inputs")["run"]

        valid = _run(
            ["bash", "-euo", "pipefail", "-c", validation],
            env=_workflow_env(FORECAST_CUTOFF="2026-08-01"),
            check=False,
        )
        self.assertEqual(valid.returncode, 0, valid.stderr)

        invalid_cases = (
            {"FORECAST_SEASON": "26"},
            {"FORECAST_SEASON": "2026; touch injected"},
            {"FORECAST_SIMULATIONS": "0"},
            {"FORECAST_SIMULATIONS": "100; touch injected"},
            {"FORECAST_CUTOFF": "2026-02-30"},
            {"FORECAST_CUTOFF": "2026-8-1"},
            {
                "FORECAST_SEASON": "2025",
                "REFRESH_SPORTSDATAVERSE": "true",
            },
            {"FORECAST_SEASON": "2024", "REFRESH_PBPSTATS": "true"},
        )
        for overrides in invalid_cases:
            with self.subTest(overrides=overrides):
                result = _run(
                    ["bash", "-euo", "pipefail", "-c", validation],
                    env=_workflow_env(**overrides),
                    check=False,
                )
                self.assertNotEqual(result.returncode, 0)

    def test_dispatch_strings_reach_shell_only_through_environment(self) -> None:
        workflow_text = WORKFLOW_PATH.read_text(encoding="utf-8")
        workflow = _load_workflow()
        job = workflow["jobs"]["standings-playoff-forecast"]  # type: ignore[index]
        self.assertEqual(
            job["env"],
            {
                "FORECAST_SEASON": "${{ inputs.season }}",
                "FORECAST_CUTOFF": "${{ inputs.cutoff }}",
                "FORECAST_SIMULATIONS": "${{ inputs.simulations }}",
                "REFRESH_SPORTSDATAVERSE": "${{ inputs.refresh_sportsdataverse }}",
                "REFRESH_PBPSTATS": "${{ inputs.refresh_pbpstats }}",
            },
        )
        for step in _steps(workflow):
            if "run" not in step:
                continue
            for input_name in ("season", "cutoff", "simulations"):
                self.assertNotIn(f"${{{{ inputs.{input_name} }}}}", step["run"])
        self.assertIn('ARGS=(--season "$FORECAST_SEASON"', workflow_text)

    def test_refresh_test_build_and_upload_gates_are_ordered(self) -> None:
        workflow = _load_workflow()
        steps = _steps(workflow)
        names = [step.get("uses", step.get("name")) for step in steps]

        sports = _named_step(workflow, "Refresh SportsDataverse")
        self.assertEqual(
            sports["if"],
            "${{ inputs.refresh_sportsdataverse && inputs.season == '2026' }}",
        )
        self.assertEqual(
            sports["run"], "python scripts/fetch_wnba_sportsdataverse_2026.py"
        )
        pbp = _named_step(workflow, "Refresh PBPStats")
        self.assertEqual(
            pbp["if"], "${{ inputs.refresh_pbpstats && inputs.season == '2026' }}"
        )
        self.assertEqual(
            pbp["run"].splitlines(),
            [
                "python scripts/pbpstats_2026_pull_clean.py",
                "python scripts/pbpstats_2026_features.py",
            ],
        )
        tests = _named_step(workflow, "Run forecast tests")
        self.assertEqual(tests["if"], "${{ inputs.run_tests }}")
        self.assertEqual(
            tests["run"],
            'python -m unittest discover -s tests -p "test_standings_playoff_forecast*.py"',
        )

        required_order = [
            "Validate inputs",
            "Refresh SportsDataverse",
            "Refresh PBPStats",
            "Run forecast tests",
            "Build forecast and deliverables",
            "Validate forecast artifacts",
            "actions/upload-artifact@v7",
            "Commit forecast outputs if requested",
        ]
        positions = [names.index(item) for item in required_order]
        self.assertEqual(positions, sorted(positions))

        upload_index = names.index("actions/upload-artifact@v7")

        upload = steps[upload_index]
        self.assertEqual(
            upload["with"]["name"],
            "wnba-standings-forecast-${{ inputs.season }}-${{ github.run_id }}",
        )
        self.assertEqual(
            upload["with"]["path"].splitlines(),
            [
                "analysis/standings_playoff_forecast/deliverables/season=${{ inputs.season }}/latest/**",
                "analysis/standings_playoff_forecast/data/processed/season=${{ inputs.season }}/latest/run_manifest.json",
            ],
        )
        self.assertEqual(upload["with"]["if-no-files-found"], "error")
        commit = _named_step(workflow, "Commit forecast outputs if requested")
        self.assertEqual(commit["if"], "${{ inputs.commit_outputs }}")

    def test_preupload_validation_requires_every_nonempty_artifact(self) -> None:
        workflow = _load_workflow()
        validation = _named_step(workflow, "Validate forecast artifacts")["run"]

        def materialize(root: Path) -> None:
            for relative in REQUIRED_ARTIFACTS:
                destination = root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(b"validated-artifact\n")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            materialize(root)
            complete = _run(
                ["bash", "-euo", "pipefail", "-c", validation],
                cwd=root,
                env=_workflow_env(),
                check=False,
            )
            self.assertEqual(complete.returncode, 0, complete.stderr)

            for relative in REQUIRED_ARTIFACTS:
                with self.subTest(relative=relative, failure="missing"):
                    target = root / relative
                    target.unlink()
                    missing = _run(
                        ["bash", "-euo", "pipefail", "-c", validation],
                        cwd=root,
                        env=_workflow_env(),
                        check=False,
                    )
                    self.assertNotEqual(missing.returncode, 0)
                    target.write_bytes(b"validated-artifact\n")

                with self.subTest(relative=relative, failure="empty"):
                    target.write_bytes(b"")
                    empty = _run(
                        ["bash", "-euo", "pipefail", "-c", validation],
                        cwd=root,
                        env=_workflow_env(),
                        check=False,
                    )
                    self.assertNotEqual(empty.returncode, 0)
                    target.write_bytes(b"validated-artifact\n")

    def test_build_array_preserves_argument_boundaries_and_optional_cutoff(self) -> None:
        workflow = _load_workflow()
        build = _named_step(workflow, "Build forecast and deliverables")["run"]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            capture = root / "args.txt"
            fake_python = bin_dir / "python"
            fake_python.write_text(
                '#!/usr/bin/env bash\nprintf "%s\\n" "$@" > "$CAPTURE_PATH"\n',
                encoding="utf-8",
            )
            fake_python.chmod(0o755)
            env = _workflow_env()
            env["PATH"] = f"{bin_dir}:{env['PATH']}"
            env["CAPTURE_PATH"] = str(capture)

            result = _run(
                ["bash", "-euo", "pipefail", "-c", build],
                env=env,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                capture.read_text(encoding="utf-8").splitlines(),
                [
                    "scripts/build_standings_playoff_forecast.py",
                    "--season",
                    "2026",
                    "--simulations",
                    "100000",
                    "--render",
                    "all",
                ],
            )

            env["FORECAST_CUTOFF"] = "2026-08-01"
            result = _run(
                ["bash", "-euo", "pipefail", "-c", build],
                env=env,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            args = capture.read_text(encoding="utf-8").splitlines()
            self.assertEqual(args[-2:], ["--cutoff", "2026-08-01"])
            self.assertEqual(args.count("--cutoff"), 1)

    def test_commit_step_fails_closed_and_commits_only_allowed_paths(self) -> None:
        workflow = _load_workflow()
        commit = _named_step(workflow, "Commit forecast outputs if requested")["run"]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            remote = root / "remote.git"
            checkout = root / "checkout"
            _run(["git", "init", "--bare", str(remote)])
            checkout.mkdir()
            _run(["git", "init", "-b", "forecast-branch"], cwd=checkout)
            _run(["git", "config", "user.name", "Test User"], cwd=checkout)
            _run(["git", "config", "user.email", "test@example.com"], cwd=checkout)
            _run(["git", "remote", "add", "origin", str(remote)], cwd=checkout)

            allowed = [
                Path("analysis/standings_playoff_forecast/data/processed/season=2026/latest/payload.json"),
                Path("analysis/standings_playoff_forecast/deliverables/season=2026/latest/brief.md"),
                Path("data/processed/wnba_team_game/season=2026/team_game.parquet"),
            ]
            raw = Path("data/raw/sportsdataverse/wnba_2026/schedule.parquet")
            unrelated = Path("notes.txt")
            for path in [*allowed, raw, unrelated]:
                destination = checkout / path
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text("before\n", encoding="utf-8")
            _run(["git", "add", "."], cwd=checkout)
            _run(["git", "commit", "-m", "initial"], cwd=checkout)
            _run(["git", "push", "-u", "origin", "forecast-branch"], cwd=checkout)

            for path in [*allowed, raw, unrelated]:
                (checkout / path).write_text("after\n", encoding="utf-8")
            env = _workflow_env()
            env.update(
                {"GITHUB_REF_TYPE": "branch", "GITHUB_REF_NAME": "forecast-branch"}
            )
            result = _run(
                ["bash", "-euo", "pipefail", "-c", commit],
                cwd=checkout,
                env=env,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            changed = _run(
                ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"],
                cwd=checkout,
            ).stdout.splitlines()
            self.assertEqual(changed, sorted(str(path) for path in allowed))
            status = _run(["git", "status", "--short"], cwd=checkout).stdout
            self.assertIn(str(raw), status)
            self.assertIn(str(unrelated), status)
            remote_head = _run(
                ["git", "--git-dir", str(remote), "rev-parse", "refs/heads/forecast-branch"]
            ).stdout.strip()
            local_head = _run(["git", "rev-parse", "HEAD"], cwd=checkout).stdout.strip()
            self.assertEqual(remote_head, local_head)

            tag_env = env | {"GITHUB_REF_TYPE": "tag", "GITHUB_REF_NAME": "v1"}
            rejected = _run(
                ["bash", "-euo", "pipefail", "-c", commit],
                cwd=checkout,
                env=tag_env,
                check=False,
            )
            self.assertNotEqual(rejected.returncode, 0)


if __name__ == "__main__":
    unittest.main()
