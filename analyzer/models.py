from django.db import models


class Scan(models.Model):
    """
    A single 'run' of the code-graph analyzer over a project.
    The full computed graph (nodes + edges + stats) is stored as JSON
    so the frontend can render it instantly without re-parsing anything.
    """
    name = models.CharField(max_length=255, default="Untitled Project")
    source_label = models.CharField(
        max_length=255,
        help_text="Either 'sample_project' or the uploaded zip filename",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    total_files = models.IntegerField(default=0)
    total_nodes = models.IntegerField(default=0)
    total_edges = models.IntegerField(default=0)
    dead_code_count = models.IntegerField(default=0)
    cycle_count = models.IntegerField(default=0)

    # Full graph payload: {"nodes": [...], "edges": [...], "stats": {...}}
    result_json = models.JSONField(default=dict)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} ({self.created_at:%Y-%m-%d %H:%M})"
