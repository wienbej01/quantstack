"""QX CLI - QuantStack Command Line Interface."""

import typer

from qx_cli.exp import app as exp_app

__version__ = "0.1.0"

app = typer.Typer()
app.add_typer(exp_app, name="exp", help="Experiments harness commands")

if __name__ == "__main__":
    app()
