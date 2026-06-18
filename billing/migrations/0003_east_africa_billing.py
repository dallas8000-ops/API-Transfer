from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("billing", "0002_workspace_customer_default_workspace_workspacemember_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="customer",
            name="paystack_customer_code",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="subscription",
            name="payment_provider",
            field=models.CharField(
                choices=[("stripe", "stripe"), ("paystack", "paystack")],
                default="stripe",
                max_length=32,
            ),
        ),
        migrations.AddField(
            model_name="subscription",
            name="paystack_subscription_code",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AlterField(
            model_name="providerconnection",
            name="provider",
            field=models.CharField(
                choices=[
                    ("render", "render"),
                    ("railway", "railway"),
                    ("fly", "fly"),
                    ("kong", "kong"),
                    ("terraform", "terraform"),
                    ("supabase", "supabase"),
                    ("cloudflare", "cloudflare"),
                    ("stripe", "stripe"),
                    ("orena", "orena"),
                ],
                max_length=32,
            ),
        ),
    ]
