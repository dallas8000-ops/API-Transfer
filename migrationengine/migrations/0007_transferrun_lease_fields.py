from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("migrationengine", "0006_transferrun_state_machine"),
    ]

    operations = [
        migrations.AddField(
            model_name="transferrun",
            name="heartbeat_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="transferrun",
            name="lease_expires_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="transferrun",
            name="lease_owner",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
    ]
