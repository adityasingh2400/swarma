"""Playbook registry — imports all playbooks and registers them with the orchestrator.

Research: Facebook, Depop, Amazon
Listing:  Facebook only (enforced by _should_list_on_platform in orchestrator.py)
"""
from playbooks.facebook import FacebookPlaybook
from playbooks.depop import DepopPlaybook
from playbooks.amazon import AmazonPlaybook
from orchestrator import register_playbook

register_playbook(FacebookPlaybook())
register_playbook(DepopPlaybook())
register_playbook(AmazonPlaybook())
