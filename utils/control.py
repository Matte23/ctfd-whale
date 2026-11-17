import datetime
import traceback

from CTFd.utils import get_config

from .db import DBContainer, db
from .docker import DockerUtils
from .routers import Router


class ControlUtil:
    @staticmethod
    def try_add_container(user_id: int, challenge_id: int, flag_id: int):
        container = DBContainer.create_container_record(user_id, challenge_id, flag_id)
        try:
            DockerUtils.add_container(container)
        except Exception:
            print(traceback.format_exc())
            ControlUtil._discard_container(container)
            return False, "Docker Creation Error"
        try:
            ok, msg = Router.register(container)
        except Exception:
            print(traceback.format_exc())
            ok, msg = False, "Unable to register the instance, please try again later."
        if not ok:
            ControlUtil._discard_container(container)
            return False, msg
        return True, "Container created"

    @staticmethod
    def _discard_container(container):
        """Clean up after a failed creation.

        Docker resources (network, already-started containers, subnet) may exist
        even if creation failed partway, so remove them before the DB record.
        If that fails (e.g. Docker unreachable), keep the record so auto-clean
        retries the removal when the container expires.
        """
        try:
            DockerUtils.remove_container(container)
            Router.release(container)
        except Exception:
            print(traceback.format_exc())
            return
        DBContainer.remove_container_record(container)

    @staticmethod
    def try_remove_container(user_id: int):
        container = DBContainer.get_current_containers(user_id=user_id)
        if not container:
            return False, "No such container"
        for _ in range(3):  # configurable? as "onerror_retry_cnt"
            try:
                ok, msg = Router.unregister(container)
                if not ok:
                    return False, msg
                DockerUtils.remove_container(container)
                # only release the port once the old container is really gone
                Router.release(container)
                DBContainer.remove_container_record(container)
                return True, "Container destroyed"
            except Exception:
                print(traceback.format_exc())
        return False, "Failed when destroying instance, please contact admin!"

    @staticmethod
    def try_renew_container(user_id: int):
        container = DBContainer.get_current_containers(user_id)
        if not container:
            return False, "No such container"
        timeout = int(get_config("whale:docker_timeout", "3600"))
        container.start_time = container.start_time + datetime.timedelta(
            seconds=timeout
        )
        if container.start_time > datetime.datetime.now():
            container.start_time = datetime.datetime.now()
            # race condition? useless maybe?
            # useful when docker_timeout < poll timeout (10 seconds)
            # doesn't make any sense
        else:
            return False, "Invalid container"
        container.renew_count += 1
        db.session.commit()
        return True, "Container Renewed"
