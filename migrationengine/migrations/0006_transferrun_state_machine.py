from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("migrationengine", "0005_transferrun"),
    ]

    operations = [
        migrations.AddField(
            model_name="transferrun",
            name="attempt_started_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="transferrun",
            name="last_error",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="transferrun",
            name="max_retries",
            field=models.PositiveIntegerField(default=3),
        ),
        migrations.AddField(
            model_name="transferrun",
            name="next_retry_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="transferrun",
            name="retry_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="transferrun",
            name="step",
            field=models.CharField(default="queued", max_length=32),
        ),
        migrations.AddField(
            model_name="transferrun",
            name="step_state",
            field=models.JSONField(default=dict),
        ),
    ]
