from __future__ import annotations

import sys

import run_single_platform
from monitor.final_realtime_policy import install_final_realtime_policy
from monitor.unknown_comment_queue_policy import install_unknown_comment_count_fallback


def _platform_from_argv(argv: list[str]) -> str:
    for i, arg in enumerate(argv):
        if arg == "--platform" and i + 1 < len(argv):
            return str(argv[i + 1]).strip()
        if arg.startswith("--platform="):
            return arg.split("=", 1)[1].strip()
    return ""


def main() -> None:
    platform = _platform_from_argv(sys.argv[1:])

    # Kuaishou keeps its separately validated unknown-count/startup/session policy.
    # The other student platforms use the shared isolated, atomic realtime policy.
    if platform and platform != "ks":
        install_final_realtime_policy(platform)
        install_unknown_comment_count_fallback(platform)

    # run_single_platform installs its older Douyin hard-budget policy inside main().
    # The final student wrapper has already installed the newer soft-budget/atomic
    # policy, so prevent the legacy Douyin monkey patch from replacing it.
    if platform == "dy":
        run_single_platform._install_douyin_realtime_policy = lambda: None

    run_single_platform.main()


if __name__ == "__main__":
    main()
