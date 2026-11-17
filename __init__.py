import warnings

from CTFd.api import CTFd_API_v1
from CTFd.plugins import (
    register_admin_plugin_menu_bar,
    register_plugin_assets_directory,
)
from CTFd.plugins.challenges import CHALLENGE_CLASSES
from CTFd.plugins.migrations import upgrade
from CTFd.utils import set_config
from CTFd.utils.decorators import admins_only
from flask import Blueprint, render_template, request, session
from flask_apscheduler import APScheduler

from .api import AdminContainers, admin_namespace, user_namespace
from .challenge_type import DockerChallenge
from .utils.cache import job_lock
from .utils.checks import WhaleChecks
from .utils.control import ControlUtil
from .utils.db import DBContainer
from .utils.docker import docker_client
from .utils.exceptions import WhaleWarning
from .utils.routers import get_router
from .utils.setup import setup_default_configs

AUTO_CLEAN_INTERVAL_SECONDS = 10
# Upper bound of one auto-clean run; the lock expires after it in any case.
AUTO_CLEAN_LOCK_SECONDS = 300

# Layouts of the admin instances page: templates/containers/<mode>.containers.html
VIEW_MODES = ("list", "card")


def load(app):
    app.config["RESTX_ERROR_404_HELP"] = False
    plugin_name = __name__.split(".")[-1]
    set_config("whale:plugin_name", plugin_name)
    # create_all() creates missing tables; the migrations bring existing
    # tables up to date (CTFd skips them on SQLite and only runs create_all)
    app.db.create_all()
    upgrade(plugin_name=plugin_name)
    # every startup: settings added by newer versions get their default too
    setup_default_configs()

    register_plugin_assets_directory(
        app,
        base_path=f"/plugins/{plugin_name}/assets",
        endpoint="plugins.ctfd-whale.assets",
    )
    register_admin_plugin_menu_bar(
        title="Docker", route="/plugins/ctfd-whale/admin/settings"
    )

    CHALLENGE_CLASSES["docker"] = DockerChallenge

    page_blueprint = Blueprint(
        "ctfd-whale",
        __name__,
        template_folder="templates",
        static_folder="assets",
        url_prefix="/plugins/ctfd-whale",
    )
    CTFd_API_v1.add_namespace(admin_namespace, path="/plugins/ctfd-whale/admin")
    CTFd_API_v1.add_namespace(user_namespace, path="/plugins/ctfd-whale")

    @page_blueprint.route("/admin/settings")
    @admins_only
    def admin_list_configs():
        errors = WhaleChecks.perform()
        return render_template("whale_config.html", errors=errors)

    @page_blueprint.route("/admin/containers")
    @admins_only
    def admin_list_containers():
        result = AdminContainers.get()
        # the mode picks an included template: only accept known values, and
        # fall back to "list" so a bad value can't stick in the session
        view_mode = request.args.get("mode", session.get("view_mode"))
        if view_mode not in VIEW_MODES:
            view_mode = "list"
        session["view_mode"] = view_mode
        return render_template(
            "whale_containers.html",
            plugin_name=plugin_name,
            view_mode=view_mode,
            containers=result["data"]["containers"],
            pages=result["data"]["pages"],
            curr_page=abs(request.args.get("page", 1, type=int)),
            curr_page_start=result["data"]["page_start"],
        )

    def auto_clean_container():
        with app.app_context():
            # every worker runs this job: the lock lets one of them do the work
            lock = job_lock("auto-clean", timeout=AUTO_CLEAN_LOCK_SECONDS)
            if not lock.acquire():
                return
            try:
                # per container, not per user: rows of deleted users have no
                # user_id. Includes containers whose removal failed: retried here.
                for container in DBContainer.get_containers_to_clean():
                    ControlUtil.remove_container(container)
            finally:
                lock.release()

    app.register_blueprint(page_blueprint)

    try:
        docker_client()
    except Exception as e:
        warnings.warn(
            f"Docker initialization failed, check your configs: {e}",
            WhaleWarning,
            stacklevel=2,
        )
    try:
        router = get_router()
        ok, msg = router.check_availability()
        if not ok:
            warnings.warn(
                f"Router not available, check your configs: {msg}",
                WhaleWarning,
                stacklevel=2,
            )
        router.sync()
    except Exception as e:
        warnings.warn(
            f"Router initialization failed, check your configs: {e}",
            WhaleWarning,
            stacklevel=2,
        )

    scheduler = APScheduler()
    scheduler.init_app(app)
    scheduler.start()
    scheduler.add_job(
        id="whale-auto-clean",
        func=auto_clean_container,
        trigger="interval",
        seconds=AUTO_CLEAN_INTERVAL_SECONDS,
        # skip a run instead of piling them up when one takes longer
        max_instances=1,
        coalesce=True,
    )
    print("[CTFd Whale] Started successfully")
