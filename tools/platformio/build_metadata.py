"""Embed inspectable source identity in every firmware profile."""

import subprocess

Import("env")


project_dir = env.subst("$PROJECT_DIR")


def git_output(*args):
    return subprocess.check_output(
        ["git", *args], cwd=project_dir, text=True,
        stderr=subprocess.DEVNULL).strip()


try:
    git_sha = git_output("rev-parse", "--short=12", "HEAD")
    if git_output("status", "--porcelain"):
        git_sha += "-dirty"
except (OSError, subprocess.CalledProcessError):
    git_sha = "unknown"

profile = env.subst("$PIOENV")
env.Append(CPPDEFINES=[
    ("SIMPLE_KVM_GIT_SHA", '\\"%s\\"' % git_sha),
    ("SIMPLE_KVM_BUILD_PROFILE", '\\"%s\\"' % profile),
])
