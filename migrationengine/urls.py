from django.urls import path

from diagnostics.views import DiagnoseFixView, DiagnoseView

from .views import (
    ApplyView,
    AuditView,
    DeployDetectView,
    DeployView,
    DiscoverView,
    PlanView,
    RollbackView,
    TerraformApplyView,
    TerraformPlanView,
)

urlpatterns = [
    path("discover", DiscoverView.as_view(), name="discover"),
    path("plan", PlanView.as_view(), name="plan"),
    path("apply", ApplyView.as_view(), name="apply"),
    path("rollback", RollbackView.as_view(), name="rollback"),
    path("terraform/plan", TerraformPlanView.as_view(), name="terraform-plan"),
    path("terraform/apply", TerraformApplyView.as_view(), name="terraform-apply"),
    path("deploy/detect", DeployDetectView.as_view(), name="deploy-detect"),
    path("deploy", DeployView.as_view(), name="deploy"),
    path("diagnose", DiagnoseView.as_view(), name="diagnose"),
    path("diagnose/fix", DiagnoseFixView.as_view(), name="diagnose-fix"),
    path("audit", AuditView.as_view(), name="audit"),
]
