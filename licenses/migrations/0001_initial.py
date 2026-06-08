from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("billing", "0002_workspace_customer_default_workspace_workspacemember_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="License",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("key_hash", models.CharField(max_length=64, unique=True)),
                ("key_last4", models.CharField(max_length=4)),
                ("registered_domain", models.CharField(max_length=255)),
                ("max_instances", models.PositiveIntegerField(default=1)),
                (
                    "status",
                    models.CharField(
                        choices=[("active", "active"), ("revoked", "revoked"), ("expired", "expired")],
                        default="active",
                        max_length=16,
                    ),
                ),
                ("expires_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "customer",
                    models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="licenses", to="billing.customer"),
                ),
                (
                    "subscription",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=models.deletion.CASCADE,
                        related_name="license",
                        to="billing.subscription",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="LicenseInstance",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("instance_id", models.CharField(max_length=255)),
                ("domain", models.CharField(max_length=255)),
                ("first_seen_at", models.DateTimeField(auto_now_add=True)),
                ("last_seen_at", models.DateTimeField(auto_now=True)),
                ("is_active", models.BooleanField(default=True)),
                (
                    "license",
                    models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="instances", to="licenses.license"),
                ),
            ],
            options={
                "ordering": ["-last_seen_at"],
                "unique_together": {("license", "instance_id")},
            },
        ),
        migrations.AddIndex(
            model_name="license",
            index=models.Index(fields=["status"], name="licenses_lic_status_58bc43_idx"),
        ),
        migrations.AddIndex(
            model_name="license",
            index=models.Index(fields=["registered_domain"], name="licenses_lic_registe_767043_idx"),
        ),
        migrations.AddIndex(
            model_name="licenseinstance",
            index=models.Index(fields=["license", "is_active"], name="licenses_lic_license_6935b4_idx"),
        ),
        migrations.AddIndex(
            model_name="licenseinstance",
            index=models.Index(fields=["instance_id"], name="licenses_lic_instanc_00a154_idx"),
        ),
    ]
