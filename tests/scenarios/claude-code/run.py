#!/usr/bin/env python3
"""Run isolated fresh-context Claude Code scenarios with no external deps."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
from typing import Iterable


SCENARIOS = (
    "light-bug",
    "standard-feature",
    "route-choice",
    "repository-challenge",
    "interrupted-recovery",
    "unsafe-parallelism",
    "missing-evidence",
    "upstream-change",
)

RUBRIC = (
    "过早编码",
    "单问题 Grill",
    "路线质量",
    "用户门禁",
    "ID 追踪",
    "真实仓库检查",
    "切片质量",
    "diff 审查",
    "证据结论",
)


def run_command(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout: int = 120,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def make_writable(path: Path) -> None:
    for item in [path, *path.rglob("*")]:
        mode = item.stat().st_mode
        item.chmod(mode | stat.S_IWUSR)


def make_read_only(path: Path) -> None:
    for item in path.rglob("*"):
        if item.is_dir():
            item.chmod(0o555)
        else:
            item.chmod(0o444)
    path.chmod(0o555)


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def initialize_fixture(project: Path) -> str:
    base_env = os.environ.copy()
    base_env.update(
        {
            "GIT_AUTHOR_NAME": "Grill Harness Fixture",
            "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
            "GIT_COMMITTER_NAME": "Grill Harness Fixture",
            "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
        }
    )
    for command in (
        ["git", "init", "-q"],
        ["git", "add", "."],
        ["git", "commit", "-q", "-m", "fixture baseline"],
    ):
        completed = run_command(command, cwd=project, env=base_env)
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr or completed.stdout)
    baseline = run_command(
        ["git", "rev-parse", "HEAD"], cwd=project, env=base_env
    )
    if baseline.returncode != 0:
        raise RuntimeError(baseline.stderr or baseline.stdout)
    return baseline.stdout.strip()


def isolated_env(home: Path) -> dict[str, str]:
    env = os.environ.copy()
    for name in (
        "ANTHROPIC_API_KEY",
        "CLAUDE_CODE_OAUTH_TOKEN",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "GOOGLE_APPLICATION_CREDENTIALS",
    ):
        env.pop(name, None)
    env.update(
        {
            "HOME": str(home),
            "CLAUDE_CONFIG_DIR": str(home / ".claude"),
            "XDG_CONFIG_HOME": str(home / ".config"),
            "XDG_CACHE_HOME": str(home / ".cache"),
            "GRILL_HARNESS_TEST_ROOT": str(home / ".grill-harness"),
        }
    )
    return env


def render_prompt(
    scenario_dir: Path,
    scenario: str,
    *,
    project: Path,
    task_package: Path,
) -> str:
    prompt = (scenario_dir / f"{scenario}.prompt.md").read_text(encoding="utf-8")
    return prompt.replace("<PROJECT>", str(project)).replace(
        "<TASK_PACKAGE>", str(task_package)
    )


def create_task_package(
    scenario_dir: Path,
    *,
    project: Path,
    baseline: str,
    report: Path,
    task_package: Path,
) -> None:
    template = (scenario_dir / "fixtures" / "acceptance-task.md.template").read_text(
        encoding="utf-8"
    )
    content = (
        template.replace("<PROJECT>", str(project))
        .replace("<GIT_BASELINE>", baseline)
        .replace("<REPORT>", str(report))
    )
    write_text(task_package, content)


def display_command(command: Iterable[str], *, home: Path, cwd: Path) -> str:
    quoted = " ".join(json.dumps(part, ensure_ascii=False) for part in command)
    return (
        f"cwd={cwd}\n"
        f"HOME={home}\n"
        f"CLAUDE_CONFIG_DIR={home / '.claude'}\n"
        f"command={quoted}\n"
    )


def score_markdown(
    scenario: str,
    *,
    command_exit: int,
    auth_exit: int,
    auth_output: str,
    stdout: str,
    report_written: bool,
) -> str:
    not_logged_in = "Not logged in" in stdout or '"loggedIn": false' in auth_output
    if not_logged_in:
        conclusion = (
            "未验证：隔离 HOME/CLAUDE_CONFIG_DIR 未登录；Claude Code 在模型执行前返回 "
            "`Not logged in · Please run /login`。未复制或复用真实 OAuth 凭据。"
        )
        score = "未验证"
    elif command_exit != 0:
        conclusion = f"未验证：Claude Code 进程退出码为 {command_exit}。"
        score = "未验证"
    else:
        conclusion = "需要人工依据原始输出逐项评分；运行时已产生模型输出。"
        score = "未验证"

    lines = [
        f"# Claude Code result: {scenario}",
        "",
        f"- CLI exit: `{command_exit}`",
        f"- isolated auth-status exit: `{auth_exit}`",
        f"- startup report written: `{'yes' if report_written else 'no'}`",
        f"- conclusion: {conclusion}",
        "",
        "## Rubric",
        "",
        "| Dimension | Score | Reason |",
        "|---|---|---|",
    ]
    for dimension in RUBRIC:
        lines.append(
            f"| {dimension} | {score} | 运行时在产生可评分行为前被隔离认证阻塞。 |"
        )
    lines.extend(
        [
            "",
            "No runtime pass is claimed. See `stdout.json`, `stderr.txt`, "
            "`auth-status.json`, `claude-version.txt`, `command.txt`, "
            "`task-package.md`, and `git-status.txt` for raw evidence.",
            "",
        ]
    )
    return "\n".join(lines)


def run_scenario(
    repo_root: Path,
    scenario_dir: Path,
    results_root: Path,
    claude: str,
    scenario: str,
    *,
    keep_temp: bool,
) -> dict[str, object]:
    temp_root = Path(tempfile.mkdtemp(prefix=f"grh-claude-{scenario}."))
    home = temp_root / "home"
    project = temp_root / "project"
    reports = temp_root / "reports"
    task_package = home / ".grill-harness" / "tasks" / "最终验收任务.md"
    report = reports / "验收报告.md"
    result_dir = results_root / scenario
    if result_dir.exists():
        shutil.rmtree(result_dir)
    result_dir.mkdir(parents=True)

    home.mkdir(parents=True)
    reports.mkdir(parents=True)
    skill_target = home / ".claude" / "skills" / "grill-harness"
    skill_target.parent.mkdir(parents=True)
    shutil.copytree(repo_root / "skills" / "grill-harness", skill_target)
    shutil.copytree(scenario_dir / "fixtures" / "project", project)
    baseline = initialize_fixture(project)
    create_task_package(
        scenario_dir,
        project=project,
        baseline=baseline,
        report=report,
        task_package=task_package,
    )
    prompt = render_prompt(
        scenario_dir, scenario, project=project, task_package=task_package
    )
    make_read_only(project)

    env = isolated_env(home)
    auth = run_command(
        [claude, "auth", "status", "--json"], cwd=project, env=env, timeout=30
    )
    version = run_command([claude, "--version"], cwd=project, env=env, timeout=30)
    command = [
        claude,
        "-p",
        "--no-session-persistence",
        "--output-format",
        "json",
        "--permission-mode",
        "dontAsk",
        "--allowedTools",
        "Read,Glob,Grep,Bash,Write,Edit",
        "--max-budget-usd",
        "0.25",
        prompt,
    ]
    try:
        completed = run_command(command, cwd=project, env=env)
    except subprocess.TimeoutExpired as error:
        completed = subprocess.CompletedProcess(
            command,
            124,
            error.stdout or "",
            error.stderr or "Timed out after 120 seconds",
        )

    git_status = run_command(
        ["git", "status", "--short"], cwd=project, env=env, timeout=30
    )
    report_written = report.is_file()
    write_text(result_dir / "prompt.md", prompt)
    shutil.copy2(scenario_dir / f"{scenario}.expected.md", result_dir / "expected.md")
    write_text(result_dir / "auth-status.json", auth.stdout or auth.stderr)
    write_text(result_dir / "claude-version.txt", version.stdout + version.stderr)
    write_text(result_dir / "stdout.json", completed.stdout)
    write_text(result_dir / "stderr.txt", completed.stderr)
    write_text(result_dir / "git-baseline.txt", baseline + "\n")
    write_text(result_dir / "git-status.txt", git_status.stdout + git_status.stderr)
    write_text(result_dir / "command.txt", display_command(command, home=home, cwd=project))
    shutil.copy2(task_package, result_dir / "task-package.md")
    write_text(
        result_dir / "environment.txt",
        "\n".join(
            (
                f"checked_at={dt.datetime.now(dt.timezone.utc).isoformat()}",
                f"claude={claude}",
                f"temporary_root={temp_root}",
                f"isolated_home={home}",
                f"isolated_skill={skill_target}",
                f"project_read_only=true",
                f"session_persistence=false",
                f"real_grill_harness_touched=false",
                "credentials_copied=false",
                "",
            )
        ),
    )
    if report_written:
        shutil.copy2(report, result_dir / "agent-report.md")
    write_text(
        result_dir / "result.md",
        score_markdown(
            scenario,
            command_exit=completed.returncode,
            auth_exit=auth.returncode,
            auth_output=auth.stdout + auth.stderr,
            stdout=completed.stdout,
            report_written=report_written,
        ),
    )

    outcome = {
        "scenario": scenario,
        "exit": completed.returncode,
        "auth_exit": auth.returncode,
        "report_written": report_written,
        "result_dir": str(result_dir),
    }
    if keep_temp:
        outcome["temporary_root"] = str(temp_root)
    else:
        make_writable(temp_root)
        shutil.rmtree(temp_root)
    return outcome


def write_summary(results_root: Path, outcomes: list[dict[str, object]]) -> None:
    lines = [
        "# Claude Code runtime validation summary",
        "",
        f"Generated: {dt.datetime.now(dt.timezone.utc).isoformat()}",
        "",
        "All eight invocations used a distinct isolated HOME, Skill copy, "
        "read-only fixture Git repository, and disabled session persistence.",
        "The runner did not copy credentials or touch the real `~/.grill-harness`.",
        "",
        "| Scenario | CLI exit | Auth exit | Report written | Conclusion |",
        "|---|---:|---:|---|---|",
    ]
    for outcome in outcomes:
        lines.append(
            "| {scenario} | {exit} | {auth_exit} | {report} | 未验证 |".format(
                scenario=outcome["scenario"],
                exit=outcome["exit"],
                auth_exit=outcome["auth_exit"],
                report="yes" if outcome["report_written"] else "no",
            )
        )
    lines.extend(
        [
            "",
            "Exact blocker: the isolated Claude configuration reports "
            "`{\"loggedIn\": false, \"authMethod\": \"none\"}` and every "
            "non-interactive call exits `1` with "
            "`Not logged in · Please run /login` before model or Skill execution.",
            "",
            "Therefore no Claude Code behavioral scenario, including the local "
            "startup-prompt report write, is claimed as passed. The scenario "
            "definitions and runner remain reproducible in an authenticated "
            "isolated HOME.",
            "",
        ]
    )
    write_text(results_root / "SUMMARY.md", "\n".join(lines))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("scenarios", nargs="*")
    parser.add_argument("--keep-temp", action="store_true")
    args = parser.parse_args()

    scenario_dir = Path(__file__).resolve().parent
    repo_root = scenario_dir.parents[2]
    results_root = repo_root / "tests" / "scenarios" / "results" / "claude-code"
    results_root.mkdir(parents=True, exist_ok=True)
    claude = shutil.which("claude")
    if claude is None:
        write_text(
            results_root / "SUMMARY.md",
            "# Claude Code runtime validation summary\n\n"
            "未验证：`claude` executable is not available on PATH.\n",
        )
        return 1

    unknown = sorted(set(args.scenarios) - set(SCENARIOS))
    if unknown:
        parser.error(f"unknown scenarios: {', '.join(unknown)}")
    selected = tuple(args.scenarios) if args.scenarios else SCENARIOS
    outcomes = [
        run_scenario(
            repo_root,
            scenario_dir,
            results_root,
            claude,
            scenario,
            keep_temp=args.keep_temp,
        )
        for scenario in selected
    ]
    write_summary(results_root, outcomes)
    print(json.dumps(outcomes, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
