# -*- Mode:Python; indent-tabs-mode:nil; tab-width:4 -*-
#
# Copyright (C) 2015-2018 Canonical Ltd
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

import os
import pathlib
import subprocess
import sys
from unittest import mock

from testtools.matchers import Equals, MatchesRegex

from snapcraft.internal import sources
from tests import unit


class TestRpm(unit.TestCase):
    def setUp(self):
        super().setUp()
        rpm_file_path = pathlib.Path("small-0.1-1.noarch.rpm")
        rpm_file_path.touch()
        self.rpm_file_path = str(rpm_file_path)
        dst = pathlib.Path("dst")
        dst.mkdir()
        self.dest_dir = str(dst.absolute())

    @mock.patch("subprocess.check_output")
    def test_pull(self, mock_run):
        rpm_source = sources.Rpm(self.rpm_file_path, self.dest_dir)
        rpm_source.pull()

        mock_run.assert_called_once_with(
            f"rpm2cpio {self.dest_dir}/{self.rpm_file_path} | cpio -idmv",
            shell=True,
            cwd=self.dest_dir,
        )

    @mock.patch.object(sources.Rpm, "provision")
    def test_pull_rpm_must_not_clean_targets(self, mock_provision):
        rpm_source = sources.Rpm(self.rpm_file_path, self.dest_dir)
        rpm_source.pull()

        mock_provision.assert_called_once_with(
            self.dest_dir,
            clean_target=False,
            src=os.path.join(self.dest_dir, "small-0.1-1.noarch.rpm"),
        )

    def test_has_source_handler_entry_on_linux(self):
        if sys.platform == "linux":
            self.assertTrue(sources._source_handler["rpm"] is sources.Rpm)
        else:
            self.assertRaises(KeyError, sources._source_handler["rpm"])

    @mock.patch("subprocess.check_output")
    def test_pull_failure(self, mock_run):
        mock_run.side_effect = subprocess.CalledProcessError(1, [])

        rpm_source = sources.Rpm(self.rpm_file_path, self.dest_dir)
        raised = self.assertRaises(sources.errors.SnapcraftPullError, rpm_source.pull)
        self.assertThat(
            raised.command,
            MatchesRegex("rpm2cpio .*/dst/small-0.1-1.noarch.rpm | cpio -idmv"),
        )
        self.assertThat(raised.exit_code, Equals(1))
