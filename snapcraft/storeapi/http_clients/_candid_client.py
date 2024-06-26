import base64
import json
import os
import pathlib
from typing import Optional, TextIO
from urllib.parse import urlparse

import requests
import macaroonbakery._utils as utils
from macaroonbakery import bakery, httpbakery
from xdg import BaseDirectory

from snapcraft.storeapi import constants
from . import agent, errors, _config, _http_client


class WebBrowserWaitingInteractor(httpbakery.WebBrowserInteractor):
    """WebBrowserInteractor implementation using .http_client.Client.

    Waiting for a token is implemented using _http_client.Client which mounts
    a session with backoff retires.

    Better exception classes and messages are  provided to handle errors.
    """

    # TODO: transfer implementation to macaroonbakery.
    def _wait_for_token(self, ctx, wait_token_url):
        request_client = _http_client.Client()
        resp = request_client.request("GET", wait_token_url)
        if resp.status_code != 200:
            raise errors.TokenTimeoutError(url=wait_token_url)
        json_resp = resp.json()
        kind = json_resp.get("kind")
        if kind is None:
            raise errors.TokenKindError(url=wait_token_url)
        token_val = json_resp.get("token")
        if token_val is None:
            token_val = json_resp.get("token64")
            if token_val is None:
                raise errors.TokenValueError(url=wait_token_url)
            token_val = base64.b64decode(token_val)
        return httpbakery._interactor.DischargeToken(kind=kind, value=token_val)


class CandidConfig(_config.Config):
    """Hold configuration options in sections.

    There can be two sections for the sso related credentials: production and
    staging. This is governed by the STORE_DASHBOARD_URL environment
    variable. Other sections are ignored but preserved.

    """

    def _get_section_name(self) -> str:
        url = os.getenv("STORE_DASHBOARD_URL", constants.STORE_DASHBOARD_URL)
        return urlparse(url).netloc

    def _get_config_path(self) -> pathlib.Path:
        return pathlib.Path(BaseDirectory.save_config_path("snapcraft")) / "candid.cfg"


class CandidClient(_http_client.Client):
    @classmethod
    def has_credentials(cls) -> bool:
        return not CandidConfig().is_section_empty()

    @property
    def _macaroon(self) -> Optional[str]:
        return self._conf.get("macaroon")

    @_macaroon.setter
    def _macaroon(self, macaroon: str) -> None:
        self._conf.set("macaroon", macaroon)
        if self._conf_save:
            self._conf.save()

    @property
    def _auth(self) -> Optional[str]:
        return self._conf.get("auth")

    @_auth.setter
    def _auth(self, auth: str) -> None:
        self._conf.set("auth", auth)
        if self._conf_save:
            self._conf.save()

    def __init__(
        self, *, user_agent: str = agent.get_user_agent(), bakery_client=None
    ) -> None:
        super().__init__(user_agent=user_agent)

        if bakery_client is None:
            self.bakery_client = httpbakery.Client(
                interaction_methods=[WebBrowserWaitingInteractor()]
            )
        else:
            self.bakery_client = bakery_client
        self._conf = CandidConfig()
        self._conf_save = True

    def _login(self, macaroon: str) -> None:
        bakery_macaroon = bakery.Macaroon.from_dict(json.loads(macaroon))
        discharges = bakery.discharge_all(
            bakery_macaroon, self.bakery_client.acquire_discharge
        )

        # serialize macaroons the bakery-way
        discharged_macaroons = (
            "[" + ",".join(map(utils.macaroon_to_json_string, discharges)) + "]"
        )

        self._auth = base64.urlsafe_b64encode(
            utils.to_bytes(discharged_macaroons)
        ).decode("ascii")
        self._macaroon = macaroon

    def login(
        self,
        *,
        macaroon: Optional[str] = None,
        config_fd: Optional[TextIO] = None,
        save: bool = True,
    ) -> None:
        self._conf_save = save
        if macaroon is not None:
            self._login(macaroon)
        elif config_fd is not None:
            self._conf.load(config_fd=config_fd)
            if save:
                self._conf.save()
        else:
            raise RuntimeError("Logic Error")

    def request(
        self, method, url, params=None, headers=None, auth_header=True, **kwargs
    ) -> requests.Response:
        if headers and auth_header:
            headers["Macaroons"] = self._auth
        elif auth_header:
            headers = {"Macaroons": self._auth}

        response = super().request(
            method, url, params=params, headers=headers, **kwargs
        )

        if not response.ok and response.status_code == 401:
            self.login(macaroon=self._macaroon)

            response = super().request(
                method, url, params=params, headers=headers, **kwargs
            )

        return response

    def export_login(self, *, config_fd: TextIO, encode: bool):
        self._conf.save(config_fd=config_fd, encode=encode)

    def logout(self) -> None:
        self._conf.clear()
        self._conf.save()
