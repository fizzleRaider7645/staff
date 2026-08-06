{% if architecture %}
## Architecture

{{ architecture }}
{% endif %}

{% if task %}
## Task {{ task.id }}: {{ task.title }}

{{ task.description }}

### Files
{% for f in task.files %}
- {{ f }}
{% endfor %}

### Acceptance Criteria
{% for c in task.acceptance_criteria %}
- {{ c }}
{% endfor %}
{% else %}
## All Pending Tasks

{% for t in tasks %}
### Task {{ t.id }}: {{ t.title }}
{{ t.description }}

{% endfor %}
{% endif %}

Implement the above. Edit files as needed. Do not run tests yet — that happens in the verify phase.
