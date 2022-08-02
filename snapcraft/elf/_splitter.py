# -*- Mode:Python; indent-tabs-mode:nil; tab-width:4 -*-
#
# Copyright 2020-2022 Canonical Ltd.
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

"""Use patchelf to patch ELF files."""

import os
import shlex
import subprocess
from pathlib import Path
from typing import List, Optional

from craft_cli import emit

from snapcraft import utils

from . import errors
from ._elf_file import ElfFile


class DebugSplitter:
    """Split debug info from ELF files.

    :param arch_triplet: Project's arch triplet, used to determine which
           objcopy and strip command to use.
    :param debug_dir: Directory to save artifacts to.
    """

    def __init__(self, *, arch_triplet: str, debug_dir: Path) -> None:
        self.objcopy_cmd = _command_for_arch("objcopy", arch_triplet)
        self.strip_cmd = _command_for_arch("strip", arch_triplet)
        self.debug_dir = debug_dir

    def _get_debug_file_path(self, build_id: str) -> Path:
        return Path(self.debug_dir, build_id[:2], build_id[2:] + ".debug")

    def _make_debug(self, elf_file: ElfFile, debug_file: str) -> None:
        _run(
            [
                self.objcopy_cmd,
                "--only-keep-debug",
                "--compress-debug-sections",
                str(elf_file.path),
                debug_file,
            ]
        )

    def _attach_debug(self, elf_file: ElfFile, debug_file: str) -> None:
        _run([self.objcopy_cmd, "--add-gnu-debuglink", debug_file, str(elf_file.path)])

    def _strip_debug_command(self, elf_file: ElfFile) -> None:
        # dh_strip use 0o111 to verify executable:
        # https://github.com/Debian/debhelper/blob/423cfce04719f41d7224d75155c4e7f9a97a10e9/dh_strip#L229
        if os.stat(elf_file.path).st_mode & 0o111 == 0o111:
            # Executable.
            cmd = [
                self.strip_cmd,
                "--remove-section=.comment",
                "--remove-section=.note",
                str(elf_file.path),
            ]
        else:
            # Shared object.
            cmd = [
                self.strip_cmd,
                "--remove-section=.comment",
                "--remove-section=.note",
                "--strip-unneeded",
                str(elf_file.path),
            ]

        _run(cmd)

    def split(self, elf_file: ElfFile) -> Optional[Path]:
        """Perform debug information splitting.

        :param elf_file: ELF file to extract debug information from.
        :return: The path to file containing the extracted debug information.
        """
        # Matching the pattern used in dh_strip:
        # https://github.com/Debian/debhelper/blob/master/dh_strip#L359

        if not elf_file.has_debug_info:
            emit.debug(f"No debug info found for {str(elf_file.path)!r}.")
            return None

        if not elf_file.build_id:
            emit.debug(
                f"No debug info extracted for {str(elf_file.path)!r} due to missing build-id."
            )
            return None

        if elf_file.elf_type not in ["ET_EXEC", "ET_DYN"]:
            emit.progress(
                f"Skip debug extraction for {str(elf_file.path)!r} with "
                f"ELF type {elf_file.elf_type!r}",
                permanent=True,
            )
            return None

        debug_file = self._get_debug_file_path(elf_file.build_id)
        debug_file.parent.mkdir(exist_ok=True, parents=True)

        # Copy debug information to debug directory.
        self._make_debug(elf_file, debug_file.as_posix())

        # Strip debug from binary.
        self._strip_debug_command(elf_file)

        # Link/attach debug symbol file to executable.
        self._attach_debug(elf_file, debug_file.as_posix())

        return debug_file


def _command_for_arch(cmd: str, arch_triplet: Optional[str]) -> str:
    if arch_triplet:
        cmd = f"{arch_triplet}-{cmd}"
    return utils.get_host_tool(cmd)


def _run(cmd: List[str]) -> None:
    command_string = " ".join([shlex.quote(c) for c in cmd])
    emit.debug(f"running: {command_string}")

    try:
        subprocess.check_call(cmd)
    except subprocess.CalledProcessError as call_error:
        raise errors.SplitterError(
            cmd=call_error.cmd, code=call_error.returncode
        ) from call_error
