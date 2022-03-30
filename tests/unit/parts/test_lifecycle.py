# -*- Mode:Python; indent-tabs-mode:nil; tab-width:4 -*-
#
# Copyright 2022 Canonical Ltd.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 3 as
# published by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import argparse
import textwrap
from pathlib import Path
from typing import Any, Dict
from unittest.mock import call

import pytest

from snapcraft import errors
from snapcraft.parts import lifecycle as parts_lifecycle
from snapcraft.projects import Project

_SNAPCRAFT_YAML_FILENAMES = [
    "snap/snapcraft.yaml",
    "build-aux/snap/snapcraft.yaml",
    "snapcraft.yaml",
    ".snapcraft.yaml",
]


@pytest.fixture
def snapcraft_yaml():
    def write_file(
        *, base: str, filename: str = "snap/snapcraft.yaml"
    ) -> Dict[str, Any]:
        content = textwrap.dedent(
            f"""
            name: mytest
            version: '0.1'
            base: {base}
            summary: Just some test data
            description: This is just some test data.
            grade: stable
            confinement: strict

            parts:
              part1:
                plugin: nil
            """
        )
        yaml_path = Path(filename)
        yaml_path.parent.mkdir(parents=True, exist_ok=True)
        yaml_path.write_text(content)

        return {
            "name": "mytest",
            "title": None,
            "base": base,
            "compression": "xz",
            "version": "0.1",
            "contact": None,
            "donation": None,
            "issues": None,
            "source-code": None,
            "website": None,
            "summary": "Just some test data",
            "description": "This is just some test data.",
            "type": "app",
            "confinement": "strict",
            "icon": None,
            "layout": None,
            "license": None,
            "grade": "stable",
            "architectures": [],
            "package-repositories": [],
            "assumes": [],
            "hooks": None,
            "passthrough": None,
            "apps": None,
            "plugs": None,
            "slots": None,
            "parts": {"part1": {"plugin": "nil"}},
            "epoch": None,
        }

    yield write_file


def test_config_not_found(new_dir):
    """If snapcraft.yaml is not found, raise an error."""
    with pytest.raises(errors.SnapcraftError) as raised:
        parts_lifecycle.run("pull", argparse.Namespace())

    assert str(raised.value) == (
        "Could not find snap/snapcraft.yaml. Are you sure you are in the right "
        "directory?"
    )
    assert raised.value.resolution == "To start a new project, use `snapcraft init`"


@pytest.mark.parametrize("filename", _SNAPCRAFT_YAML_FILENAMES)
def test_snapcraft_yaml_load(new_dir, snapcraft_yaml, filename, mocker):
    """Snapcraft.yaml should be parsed as a valid yaml file."""
    yaml_data = snapcraft_yaml(base="core22", filename=filename)
    run_command_mock = mocker.patch("snapcraft.parts.lifecycle._run_command")

    parts_lifecycle.run(
        "pull",
        argparse.Namespace(
            parts=["part1"], destructive_mode=True, use_lxd=False, provider=None
        ),
    )

    project = Project.unmarshal(yaml_data)

    if filename == "build-aux/snap/snapcraft.yaml":
        assets_dir = Path("build-aux/snap")
    else:
        assets_dir = Path("snap")

    assert run_command_mock.mock_calls == [
        call(
            "pull",
            project=project,
            assets_dir=assets_dir,
            parsed_args=argparse.Namespace(
                parts=["part1"], destructive_mode=True, use_lxd=False, provider=None
            ),
        ),
    ]


def test_snapcraft_yaml_parse_error(new_dir, snapcraft_yaml, mocker):
    """If snapcraft.yaml is not a valid yaml, raise an error."""
    snapcraft_yaml(base="invalid: true")
    run_command_mock = mocker.patch("snapcraft.parts.lifecycle._run_command")

    with pytest.raises(errors.SnapcraftError) as raised:
        parts_lifecycle.run("pull", argparse.Namespace(parts=["part1"]))

    assert str(raised.value) == (
        "YAML parsing error: mapping values are not allowed here\n"
        '  in "snap/snapcraft.yaml", line 4, column 14'
    )
    assert run_command_mock.mock_calls == []


def test_legacy_base_not_core22(new_dir, snapcraft_yaml):
    """Only core22 is processed by the new code, use legacy otherwise."""
    snapcraft_yaml(base="core20")
    with pytest.raises(errors.LegacyFallback) as raised:
        parts_lifecycle.run("pull", argparse.Namespace())

    assert str(raised.value) == "base is not core22"


@pytest.mark.parametrize("cmd", ["pull", "build", "stage", "prime", "pack"])
def test_lifecycle_run_provider(cmd, snapcraft_yaml, new_dir, mocker):
    """Option --provider is not supported in core22."""
    snapcraft_yaml(base="core22")
    run_mock = mocker.patch("snapcraft.parts.PartsLifecycle.run")

    with pytest.raises(errors.SnapcraftError) as raised:
        parts_lifecycle.run(
            cmd,
            parsed_args=argparse.Namespace(
                destructive_mode=False,
                use_lxd=False,
                provider="some",
            ),
        )

    assert run_mock.mock_calls == []
    assert str(raised.value) == "Option --provider is not supported."


@pytest.mark.parametrize("cmd", ["pull", "build", "stage", "prime"])
def test_lifecycle_legacy_run_provider(cmd, snapcraft_yaml, new_dir, mocker):
    """Option --provider is supported by legacy."""
    snapcraft_yaml(base="core20")
    run_mock = mocker.patch("snapcraft.parts.PartsLifecycle.run")

    with pytest.raises(errors.LegacyFallback) as raised:
        parts_lifecycle.run(
            cmd,
            parsed_args=argparse.Namespace(
                destructive_mode=False,
                use_lxd=False,
                provider="some",
            ),
        )

    assert run_mock.mock_calls == []
    assert str(raised.value) == "base is not core22"


@pytest.mark.parametrize(
    "cmd,step",
    [
        ("pull", "pull"),
        ("build", "build"),
        ("stage", "stage"),
        ("prime", "prime"),
    ],
)
def test_lifecycle_run_command_step(cmd, step, snapcraft_yaml, new_dir, mocker):
    project = Project.unmarshal(snapcraft_yaml(base="core22"))
    run_mock = mocker.patch("snapcraft.parts.PartsLifecycle.run")
    mocker.patch("snapcraft.meta.snap_yaml.write")
    pack_mock = mocker.patch("snapcraft.pack.pack_snap")

    parts_lifecycle._run_command(
        cmd,
        project=project,
        assets_dir=Path(),
        parsed_args=argparse.Namespace(destructive_mode=True, use_lxd=False),
    )

    assert run_mock.mock_calls == [call(step)]
    assert pack_mock.mock_calls == []


def test_lifecycle_run_command_pack(snapcraft_yaml, new_dir, mocker):
    project = Project.unmarshal(snapcraft_yaml(base="core22"))
    run_mock = mocker.patch("snapcraft.parts.PartsLifecycle.run")
    mocker.patch("snapcraft.meta.snap_yaml.write")
    pack_mock = mocker.patch("snapcraft.pack.pack_snap")

    parts_lifecycle._run_command(
        "pack",
        project=project,
        assets_dir=Path(),
        parsed_args=argparse.Namespace(
            directory=None,
            output=None,
            destructive_mode=True,
            use_lxd=False,
        ),
    )

    assert run_mock.mock_calls == [call("prime")]
    assert pack_mock.mock_calls == [
        call(new_dir / "prime", output=None, compression="xz")
    ]


def test_lifecycle_pack_destructive_mode(snapcraft_yaml, new_dir, mocker):
    project = Project.unmarshal(snapcraft_yaml(base="core22"))
    run_in_provider_mock = mocker.patch("snapcraft.parts.lifecycle._run_in_provider")
    run_mock = mocker.patch("snapcraft.parts.PartsLifecycle.run")
    pack_mock = mocker.patch("snapcraft.pack.pack_snap")
    mocker.patch("snapcraft.meta.snap_yaml.write")
    mocker.patch("snapcraft.utils.is_managed_mode", return_value=True)
    mocker.patch(
        "snapcraft.utils.get_managed_environment_home_path",
        return_value=new_dir / "home",
    )

    parts_lifecycle._run_command(
        "pack",
        project=project,
        assets_dir=Path(),
        parsed_args=argparse.Namespace(
            directory=None,
            output=None,
            destructive_mode=True,
            use_lxd=False,
        ),
    )

    assert run_in_provider_mock.mock_calls == []
    assert run_mock.mock_calls == [call("prime")]
    assert pack_mock.mock_calls == [
        call(new_dir / "home/prime", output=None, compression="xz")
    ]


def test_lifecycle_pack_managed(snapcraft_yaml, new_dir, mocker):
    project = Project.unmarshal(snapcraft_yaml(base="core22"))
    run_in_provider_mock = mocker.patch("snapcraft.parts.lifecycle._run_in_provider")
    run_mock = mocker.patch("snapcraft.parts.PartsLifecycle.run")
    pack_mock = mocker.patch("snapcraft.pack.pack_snap")
    mocker.patch("snapcraft.meta.snap_yaml.write")
    mocker.patch("snapcraft.utils.is_managed_mode", return_value=True)
    mocker.patch(
        "snapcraft.utils.get_managed_environment_home_path",
        return_value=new_dir / "home",
    )

    parts_lifecycle._run_command(
        "pack",
        project=project,
        assets_dir=Path(),
        parsed_args=argparse.Namespace(
            directory=None,
            output=None,
            destructive_mode=False,
            use_lxd=False,
        ),
    )

    assert run_in_provider_mock.mock_calls == []
    assert run_mock.mock_calls == [call("prime")]
    assert pack_mock.mock_calls == [
        call(new_dir / "home/prime", output=None, compression="xz")
    ]


def test_lifecycle_pack_not_managed(snapcraft_yaml, new_dir, mocker):
    project = Project.unmarshal(snapcraft_yaml(base="core22"))
    run_in_provider_mock = mocker.patch("snapcraft.parts.lifecycle._run_in_provider")
    run_mock = mocker.patch("snapcraft.parts.PartsLifecycle.run")
    mocker.patch("snapcraft.utils.is_managed_mode", return_value=False)

    parts_lifecycle._run_command(
        "pack",
        project=project,
        assets_dir=Path(),
        parsed_args=argparse.Namespace(
            directory=None,
            output=None,
            destructive_mode=False,
            use_lxd=False,
        ),
    )

    assert run_mock.mock_calls == []
    assert run_in_provider_mock.mock_calls == [
        call(
            project,
            "pack",
            argparse.Namespace(
                directory=None,
                output=None,
                destructive_mode=False,
                use_lxd=False,
            ),
        )
    ]