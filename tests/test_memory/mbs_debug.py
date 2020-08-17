from __future__ import absolute_import, print_function

import koji
import mock
import signal
import threading
import types

from module_build_service import app
from module_build_service.common import conf
from module_build_service.builder import GenericBuilder

from tests.test_build.test_build import FakeModuleBuilder
from tests.test_build.test_build import main as run_scheduler


def patch_config_system_setter():
    """bypass supported builders check"""
    def set_system(self, system):
        self._system = system
    conf._setifok_system = types.MethodType(set_system, conf)


def register_fake_builder():
    patch_config_system_setter()
    conf.system = FakeModuleBuilder.backend
    GenericBuilder.register_backend_class(FakeModuleBuilder)

    # Builder always instantly succeeds
    def on_get_task_info_cb(cls, task_id):
        return {"state": koji.TASK_STATES["CLOSED"]}
    FakeModuleBuilder.on_get_task_info_cb = on_get_task_info_cb


class SimpleMock:
    """Dummy callable mock object - we want our memory footprint to be as small as possible"""
    def __call__(self, *args, **kwargs):
        return True


@mock.patch("module_build_service.scheduler.handlers.modules.handle_stream_collision_modules",
            new_callable=SimpleMock)
@mock.patch("module_build_service.scheduler.handlers.modules.record_module_build_arches",
            new_callable=SimpleMock)
@mock.patch("module_build_service.scheduler.greenwave.Greenwave.check_gating",
            new_callable=SimpleMock)
def run_debug_instance(mock_1, mock_2, mock_3, host=None, port=None):

    def handle_pdb(sig, frame):
        import pdb
        pdb.Pdb().set_trace(frame)

    # kill -10 <PID> to start debugger
    signal.signal(signal.SIGUSR1, handle_pdb)

    register_fake_builder()

    host = host or conf.host
    port = port or conf.port

    def run_app():
        app.run(host=host, port=port, debug=False)
    threading.Thread(target=run_app, daemon=True).start()

    # run moksha hub and never stop
    run_scheduler([], stop_condition=lambda msg: False)


if __name__ == '__main__':
    run_debug_instance()
