"""Isolated native Dashboard for browser tests; never use real project state."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import socket
import sys

from test_workflow import REPOSITORY, WorkflowTest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets",type=Path,required=True)
    parser.add_argument("--info",type=Path,required=True)
    args=parser.parse_args()
    if not (args.assets/"index.html").is_file():
        parser.error("a built native Dashboard frontend is required")
    fixture=WorkflowTest()
    fixture.setUp()
    try:
        original=fixture.manifest
        fixture.manifest=fixture.workflow.submit("离线演示 · 修复任务去重并补充回归验证","browser-main")
        fixture.execution=fixture.manifest["execution_id"]
        fixture.finish()
        fixture.workflow.accept(fixture.execution)
        blocked=fixture.workflow.submit("离线演示 · 排查审查版本不一致","browser-blocked")
        from hermes_cli import kanban_db as kb
        fixture.workflow.start(blocked["execution_id"],True)
        with kb.connect_closing(board="default") as conn:
            kb.recompute_ready(conn)
            research=blocked["rounds"][0]["tasks"]["researcher"]
            assert kb.claim_task(conn,research) is not None
            assert kb.complete_task(conn,research,result="fixture research")
            kb.recompute_ready(conn)
            assert kb.block_task(conn,blocked["rounds"][0]["tasks"]["builder"],reason="fixture: needs independent review")
        # Existing triage fixture stays isolated and clearly labelled.
        original["objective"]="离线演示 · 待审批的研发目标"
        fixture.workflow.save(original)
        env_file=fixture.directory/"browser.env"
        env_file.write_text("\n".join(f"{key}={value}" for key,value in fixture.env.items())+"\n",encoding="utf-8")
        spec=importlib.util.spec_from_file_location("browser_app_installer",REPOSITORY/"scripts/install-workflow-app.py")
        installer=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(installer)
        from hermes_cli import kanban_db
        archive=Path(str(Path(kanban_db.__file__).resolve().parents[1])+".tar.gz")
        installer.install(fixture.root,env_file,archive=archive if archive.is_file() else None)
        import yaml
        (fixture.root/"config.yaml").write_text(yaml.safe_dump({"plugins":{"enabled":["workflow"]}}),encoding="utf-8")
        os.environ["HERMES_WEB_DIST"]=str(args.assets.resolve())
        os.environ["HERMES_DESKTOP"]="0"
        from hermes_cli import web_server
        import uvicorn
        # Bind once, retain the socket, and let the browser read only its port.
        server_socket=socket.socket()
        server_socket.bind(("127.0.0.1",0))
        port=server_socket.getsockname()[1]
        args.info.parent.mkdir(parents=True,exist_ok=True)
        args.info.write_text(json.dumps({"port":port,"home":str(fixture.root),"execution":fixture.execution,
                                         "goal":fixture.manifest["objective"]}),encoding="utf-8")
        server=uvicorn.Server(uvicorn.Config(web_server.app,host="127.0.0.1",port=port,access_log=False,log_level="warning"))
        server.run(sockets=[server_socket])
    finally:
        fixture.doCleanups()


if __name__ == "__main__":
    main()
