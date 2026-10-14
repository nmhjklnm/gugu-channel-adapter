import os
import sys

from . import docs, server

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PROFILES = os.environ.get("PROFILES_DIR") or os.path.join(HERE, "..", "..", "profiles")


def main(argv=None):
    argv = argv or sys.argv[1:]
    if not argv or argv[0] not in ("serve", "docs"):
        print("用法: python -m channel_adapter serve   (环境变量 PROFILE / BIND / PORT [/ UPSTREAM / PROFILES_DIR])\n"
              "      python -m channel_adapter docs    (生成 docs/adapters.md 的内容到 stdout)")
        return 2
    if argv[0] == "docs":
        sys.stdout.write(docs.render(DEFAULT_PROFILES))
        return 0
    profile = server.load_profile(os.environ["PROFILE"], DEFAULT_PROFILES)
    server.serve(profile, os.environ.get("BIND", "127.0.0.1"), int(os.environ.get("PORT", "18770")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
