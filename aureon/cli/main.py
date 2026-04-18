#!/usr/bin/env python3
"""
aureon-agent — CLI inspection surface for Aureon RANGER_AGENTS registry.

Usage:
    aureon-agent list [ranger]
    aureon-agent describe <role_id>
    aureon-agent call <role_id> <method> --input <path.json>
"""

import argparse
import inspect
import json
import sys
import threading
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path


def _discover_registries() -> dict:
    """Discover all *_AGENTS registries from aureon.agents tier subpackages."""
    registries = {}
    try:
        from aureon.agents.ranger import RANGER_AGENTS
        registries.update(RANGER_AGENTS)
    except ImportError:
        pass
    try:
        from aureon.agents.jtac import JTAC_AGENTS
        registries.update(JTAC_AGENTS)
    except ImportError:
        pass
    try:
        from aureon.agents.hunter_killer import HUNTER_KILLER_AGENTS
        registries.update(HUNTER_KILLER_AGENTS)
    except ImportError:
        pass
    return registries


def _get_task_methods(cls) -> list:
    """Get task-registry methods: public, defined on the role class itself."""
    from aureon.agents.base import Agent

    base_methods = set(dir(Agent)) | set(dir(object))
    base_methods.discard("get_status")
    always_exclude = {"prepare_settlement_package", "confirm_handoff", "emit_execution_confirmation"}

    methods = []
    for name in sorted(dir(cls)):
        if name.startswith("_"):
            continue
        if name in always_exclude:
            continue
        if name in base_methods:
            continue
        attr = getattr(cls, name, None)
        if attr is not None and callable(attr) and not isinstance(attr, (type, property)):
            methods.append(name)

    if "get_status" not in methods:
        methods.insert(0, "get_status")

    return methods


def _make_state_and_lock():
    """Create a minimal aureon_state and lock for CLI invocations."""
    state = {"doctrine_version": "1.0", "halt_active": False, "authority_log": []}
    return state, threading.Lock()


def _instantiate(cls, state=None, lock=None):
    """Instantiate an agent with a minimal aureon_state."""
    if state is None or lock is None:
        state, lock = _make_state_and_lock()
    return cls(state, lock)


def _prepare_c2_and_handoff(agent, state, lock, input_data):
    """For prepare_execution_package: auto-create C2, issue task, confirm handoff."""
    from aureon.agents.c2.coordinator import ThifurC2
    c2 = ThifurC2(state, lock)
    decision = input_data.get("decision", {})
    task_id = c2.issue_task(decision, agents=["THIFUR_J", "THIFUR_R"])
    handoff = c2.handoff(task_id, from_agent="THIFUR_J", to_agent="THIFUR_R", object_state=decision)
    agent.confirm_handoff(handoff)
    return c2, task_id


def _build_method_args(method, input_data: dict) -> tuple:
    """Build positional/keyword args for a method from JSON input."""
    sig = inspect.signature(method)
    kwargs = {}
    for name, param in sig.parameters.items():
        if name == "self":
            continue
        if name in input_data:
            kwargs[name] = input_data[name]
    return kwargs


def cmd_list(args):
    registries = _discover_registries()
    tier_filter = getattr(args, "tier", None)

    print(f"{'role_id':<30} {'role_name':<35} {'tier':<6} {'class'}")
    print("-" * 100)

    for role_id, cls in sorted(registries.items()):
        tier = getattr(cls, "tier", "?")
        if tier_filter and tier_filter == "ranger" and getattr(cls, "thifur_class", "") != "R":
            continue
        print(f"{role_id:<30} {getattr(cls, 'role_name', '?'):<35} {tier:<6} {cls.__name__}")


def cmd_describe(args):
    registries = _discover_registries()
    role_id = args.role_id

    if role_id not in registries:
        print(f"Error: role_id '{role_id}' not found in registry.", file=sys.stderr)
        sys.exit(1)

    cls = registries[role_id]
    methods = _get_task_methods(cls)

    print(f"role_id:               {cls.role_id}")
    print(f"role_name:             {getattr(cls, 'role_name', '—')}")
    print(f"tier:                  {cls.tier}")
    print(f"thifur_class:          {cls.thifur_class}")
    print(f"activated:             {cls.activated}")
    print(f"regulatory_frameworks: {getattr(cls, 'regulatory_frameworks', [])}")
    print(f"dsor_record_types:     {getattr(cls, 'dsor_record_types', [])}")
    print()
    print("Methods:")
    for name in methods:
        method = getattr(cls, name)
        sig = inspect.signature(method)
        doc = (method.__doc__ or "").strip().split("\n")[0]
        print(f"  {name}{sig}")
        if doc:
            print(f"    {doc}")


def cmd_call(args):
    registries = _discover_registries()
    role_id = args.role_id
    method_name = args.method

    if role_id not in registries:
        print(f"Error: role_id '{role_id}' not found.", file=sys.stderr)
        sys.exit(1)

    cls = registries[role_id]
    state, lock = _make_state_and_lock()
    agent = _instantiate(cls, state, lock)

    if not hasattr(agent, method_name):
        print(f"Error: method '{method_name}' not found on {role_id}.", file=sys.stderr)
        sys.exit(1)

    method = getattr(agent, method_name)

    input_data = {}
    if args.input:
        with open(args.input) as f:
            input_data = json.load(f)

    kwargs = _build_method_args(method, input_data)

    # Auto-provide C2 for methods that need it
    sig = inspect.signature(method)
    if "c2" in sig.parameters and "c2" not in kwargs:
        c2, task_id = _prepare_c2_and_handoff(agent, state, lock, input_data)
        kwargs["c2"] = c2
        if "task_id" in sig.parameters and "task_id" not in kwargs:
            kwargs["task_id"] = task_id

    t0 = time.monotonic()
    try:
        result = method(**kwargs)
    except Exception:
        traceback.print_exc()
        sys.exit(1)
    elapsed = time.monotonic() - t0

    def _serialize(obj):
        if hasattr(obj, "__dict__") and hasattr(obj, "__dataclass_fields__"):
            from dataclasses import asdict
            return asdict(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        return str(obj)

    print(json.dumps(result, indent=2, default=_serialize))
    print()
    print(f"--- metadata ---")
    print(f"role_id:  {role_id}")
    print(f"method:   {method_name}")
    print(f"elapsed:  {elapsed:.4f}s")


def main():
    parser = argparse.ArgumentParser(prog="aureon-agent", description="Aureon agent inspection CLI")
    subparsers = parser.add_subparsers(dest="command")

    # list
    p_list = subparsers.add_parser("list", help="List registered agents")
    p_list.add_argument("tier", nargs="?", help="Filter by tier (e.g. 'ranger')")

    # describe
    p_desc = subparsers.add_parser("describe", help="Describe a registered agent")
    p_desc.add_argument("role_id", help="Agent role ID")

    # call
    p_call = subparsers.add_parser("call", help="Call an agent method")
    p_call.add_argument("role_id", help="Agent role ID")
    p_call.add_argument("method", help="Method name")
    p_call.add_argument("--input", help="Path to JSON fixture file")

    args = parser.parse_args()

    if args.command == "list":
        cmd_list(args)
    elif args.command == "describe":
        cmd_describe(args)
    elif args.command == "call":
        cmd_call(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
