from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ("billing", "0002_workspace_customer_default_workspace_workspacemember_and_more"),
        ("migrationengine", "0004_deploymentrun_last_checked_at_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="TransferRun",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("run_id", models.CharField(db_index=True, max_length=64, unique=True)),
                ("mode", models.CharField(default="queue", max_length=16)),
                ("requested_by", models.CharField(default="", max_length=128)),
                ("status", models.CharField(default="pending", max_length=32)),
                ("command", models.JSONField(default=list)),
                ("options", models.JSONField(default=dict)),
                ("log_path", models.CharField(blank=True, default="", max_length=260)),
                ("exit_code", models.IntegerField(blank=True, null=True)),
                ("started_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "workspace",
                    models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="transfer_runs", to="billing.workspace"),
                ),
            ],
            options={"ordering": ["-created_at"]},
        ),
    ]
