from invoke import task


@task
def format(c):
    """Format code with ruff."""
    c.run("ruff format .")
    c.run("ruff check --fix --unsafe-fixes .")


@task
def test(c, cov=True):
    """Run tests."""
    cmd = "python -m pytest"
    if cov:
        cmd += " --cov=. --cov-report=term-missing"
    c.run(cmd, pty=False)


@task(pre=[format, test])
def all(c):
    """Format and test."""
    pass
