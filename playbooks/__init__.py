"""Playbook registry — imports all playbooks and registers them with the orchestrator."""
from playbooks.facebook import FacebookPlaybook
from orchestrator import register_playbook

register_playbook(FacebookPlaybook())
