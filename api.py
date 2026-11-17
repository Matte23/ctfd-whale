from datetime import datetime

from CTFd.plugins.ctfd_cheaters import create_flag_if_missing
from CTFd.utils import user as current_user
from CTFd.utils.decorators import (
    admins_only,
    authed_only,
    during_ctf_time_only,
    require_verified_emails,
)
from CTFd.utils.decorators.visibility import check_challenge_visibility
from flask import request
from flask_restx import Namespace, Resource, abort

from .decorators import (
    challenge_visible,
    current_challenge_id,
    frequency_limited,
    require_team_if_teams_mode,
)
from .utils.config import whale_config
from .utils.control import ControlUtil
from .utils.db import DBContainer
from .utils.flags import generate_flag
from .utils.routers import get_router

admin_namespace = Namespace("ctfd-whale-admin")
user_namespace = Namespace("ctfd-whale-user")


MAX_PER_PAGE = 100


def page_args():
    """page/per_page from the query string, clamped to valid values."""
    page = request.args.get("page", 1, type=int) or 1
    per_page = request.args.get("per_page", 20, type=int) or 20
    return max(page, 1), min(max(per_page, 1), MAX_PER_PAGE)


def serialize_container(container):
    return {
        "id": container.id,
        "name": container.name,
        "user_id": container.user_id,
        "user_name": container.user.name if container.user else None,
        "challenge_id": container.challenge_id,
        "challenge_name": container.challenge.name if container.challenge else None,
        "redirect_type": (
            container.challenge.redirect_type if container.challenge else None
        ),
        "access": container.user_access,
        "flag": container.flag.content if container.flag else None,
        "port": container.port,
        "subnet": container.subnet,
        "start_time": container.start_time.isoformat(),
        "renew_count": container.renew_count,
        "removing": container.is_removing,
    }


def not_found(message):
    # returned, not raised: flask-restx would append its "did you mean" help
    # to a raised 404
    return {"success": False, "message": message}, 404


@admin_namespace.route("/container")
class AdminContainers(Resource):
    @admins_only
    def get(self):
        page, per_page = page_args()
        pagination = DBContainer.get_alive_containers_page(page, per_page)
        return {
            "success": True,
            "data": {
                "containers": [serialize_container(c) for c in pagination.items],
                "total": pagination.total,
                "pages": pagination.pages,
                "page": pagination.page,
                "per_page": pagination.per_page,
            },
        }

    # Admin actions address containers by id, not by user: the row of a
    # deleted user has no user_id anymore.
    @staticmethod
    def _requested_container():
        """(container, None), or (None, error response)."""
        container_id = request.args.get("container_id", type=int)
        if container_id is None:
            abort(400, "Missing or invalid container_id", success=False)
        container = DBContainer.get_container_by_id(container_id)
        if container is None:
            return None, not_found("No such container")
        return container, None

    @admins_only
    def patch(self):
        container, error = self._requested_container()
        if error:
            return error
        result, message = ControlUtil.renew_container(container)
        if not result:
            abort(409, message, success=False)
        return {"success": True, "message": message}

    @admins_only
    def delete(self):
        container, error = self._requested_container()
        if error:
            return error
        result, message = ControlUtil.remove_container(container)
        return {"success": result, "message": message}


@user_namespace.route("/container")
class UserContainers(Resource):
    @authed_only
    @check_challenge_visibility
    @challenge_visible
    def get(self):
        user_id = current_user.get_current_user().id
        challenge_id = current_challenge_id()
        container = DBContainer.get_current_containers(user_id=user_id)
        if not container:
            return {"success": True, "data": {}}
        timeout = int(whale_config("docker_timeout"))
        # challenge_id is NULL when the challenge was deleted meanwhile
        if container.challenge_id != challenge_id:
            return {"success": True, "data": {}}
        return {
            "success": True,
            "data": {
                "lan_domain": container.name,
                "user_access": get_router().access(container),
                "remaining_time": timeout
                - int((datetime.now() - container.start_time).total_seconds()),
            },
        }

    @authed_only
    @check_challenge_visibility
    @during_ctf_time_only
    @require_verified_emails
    @require_team_if_teams_mode
    @challenge_visible
    @frequency_limited
    def post(self):
        user_id = current_user.get_current_user().id
        if DBContainer.get_current_containers(user_id=user_id):
            # never start a second container while the old one is still around
            result, message = ControlUtil.try_remove_container(user_id)
            if not result:
                abort(409, message, success=False)
        # also covers a removal still running elsewhere (e.g. auto-clean)
        if DBContainer.has_any_container(user_id):
            abort(
                409,
                "Your previous instance is still being destroyed, "
                "please try again in a few seconds.",
                success=False,
            )

        current_count = DBContainer.get_all_alive_container_count()
        if int(whale_config("docker_max_container_count")) <= int(current_count):
            abort(503, "Max container count exceed.", success=False)

        challenge_id = current_challenge_id()
        flag_content = generate_flag(challenge_id)
        flag_id = create_flag_if_missing(
            user_id=user_id, challenge_id=challenge_id, flag_content=flag_content
        )
        result, message, status = ControlUtil.try_add_container(
            user_id=user_id, challenge_id=challenge_id, flag_id=flag_id
        )
        if not result:
            abort(status, message, success=False)
        return {"success": True, "message": message}

    @authed_only
    @check_challenge_visibility
    @during_ctf_time_only
    @require_verified_emails
    @require_team_if_teams_mode
    @challenge_visible
    @frequency_limited
    def patch(self):
        user_id = current_user.get_current_user().id
        challenge_id = current_challenge_id()
        docker_max_renew_count = int(whale_config("docker_max_renew_count"))
        container = DBContainer.get_current_containers(user_id)
        if container is None:
            return not_found("Instance not found.")
        if container.challenge is None or container.challenge_id != challenge_id:
            other = container.challenge.name if container.challenge else "deleted"
            abort(
                409,
                f"Container started but not from this challenge ({other})",
                success=False,
            )
        if container.renew_count >= docker_max_renew_count:
            abort(403, "Max renewal count exceed.", success=False)
        result, message = ControlUtil.try_renew_container(user_id=user_id)
        return {"success": result, "message": message}

    @authed_only
    @frequency_limited
    def delete(self):
        user_id = current_user.get_current_user().id
        result, message = ControlUtil.try_remove_container(user_id)
        if not result:
            return not_found(message)
        return {"success": True, "message": message}
