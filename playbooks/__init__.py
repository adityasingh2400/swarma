"""Playbook registry — imports all playbooks and registers them with the orchestrator."""
from playbooks.ebay import EbayPlaybook
from playbooks.facebook import FacebookPlaybook
from playbooks.mercari import MercariPlaybook
from playbooks.depop import DepopPlaybook
from playbooks.amazon import AmazonPlaybook
from orchestrator import register_playbook

register_playbook(EbayPlaybook())
register_playbook(FacebookPlaybook())
register_playbook(MercariPlaybook())
register_playbook(DepopPlaybook())
register_playbook(AmazonPlaybook())
