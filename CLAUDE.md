# gstack

Use the `/browse` skill from gstack for all web browsing. Never use `mcp__claude-in-chrome__*` tools.

## Available gstack skills

- `/office-hours` - Office hours session
- `/plan-ceo-review` - CEO review planning
- `/plan-eng-review` - Engineering review planning
- `/plan-design-review` - Design review planning
- `/plan-devex-review` - DevEx review planning
- `/design-consultation` - Design consultation
- `/design-shotgun` - Design shotgun
- `/design-html` - Design to HTML
- `/review` - Code review
- `/ship` - Ship code
- `/land-and-deploy` - Land and deploy
- `/canary` - Canary deployment
- `/benchmark` - Benchmarking
- `/browse` - Web browsing
- `/connect-chrome` - Connect to Chrome
- `/qa` - QA testing
- `/qa-only` - QA only
- `/design-review` - Design review
- `/devex-review` - DevEx review
- `/setup-browser-cookies` - Set up browser cookies
- `/setup-deploy` - Set up deployment
- `/retro` - Retrospective
- `/investigate` - Investigation
- `/document-release` - Document a release
- `/codex` - Codex
- `/cso` - CSO
- `/autoplan` - Auto planning
- `/careful` - Careful mode
- `/freeze` - Freeze
- `/guard` - Guard
- `/unfreeze` - Unfreeze
- `/gstack-upgrade` - Upgrade gstack
- `/learn` - Learn

If gstack skills aren't working, run `cd .claude/skills/gstack && ./setup` to build the binary and register skills.

## Skill routing

When the user's request matches an available skill, ALWAYS invoke it using the Skill
tool as your FIRST action. Do NOT answer directly, do NOT use other tools first.
The skill has specialized workflows that produce better results than ad-hoc answers.

Key routing rules:
- Product ideas, "is this worth building", brainstorming → invoke office-hours
- Bugs, errors, "why is this broken", 500 errors → invoke investigate
- Ship, deploy, push, create PR → invoke ship
- QA, test the site, find bugs → invoke qa
- Code review, check my diff → invoke review
- Update docs after shipping → invoke document-release
- Weekly retro → invoke retro
- Design system, brand → invoke design-consultation
- Visual audit, design polish → invoke design-review
- Architecture review → invoke plan-eng-review
- Save progress, checkpoint, resume → invoke checkpoint
- Code quality, health check → invoke health
