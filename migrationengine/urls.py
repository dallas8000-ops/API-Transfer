from django.urls import path

from diagnostics.views import DiagnoseFixView, DiagnoseView

from .views import (
    AccountReviewView,
    ApplyView,
    AuditView,
    AuditExportView,
    DeploymentHistoryView,
    DeploymentStatusRefreshView,
    DeployDetectView,
    DeployView,
    DiscoverView,
    GitHubImportView,
    PlanView,
    ProviderStatusView,
    RollbackView,
    TerraformApplyView,
    TerraformPlanView,
)

urlpatterns = [
    path("discover", DiscoverView.as_view(), name="discover"),
    path("review", AccountReviewView.as_view(), name="account-review"),
    path("plan", PlanView.as_view(), name="plan"),
    path("apply", ApplyView.as_view(), name="apply"),
    path("rollback", RollbackView.as_view(), name="rollback"),
    path("terraform/plan", TerraformPlanView.as_view(), name="terraform-plan"),
    path("terraform/apply", TerraformApplyView.as_view(), name="terraform-apply"),
    path("deploy/detect", DeployDetectView.as_view(), name="deploy-detect"),
    path("github/import", GitHubImportView.as_view(), name="github-import"),
    path("deploy", DeployView.as_view(), name="deploy"),
    path("deploy/history", DeploymentHistoryView.as_view(), name="deploy-history"),
    path("deploy/status/<str:deployment_id>", DeploymentStatusRefreshView.as_view(), name="deploy-status-refresh"),
    path("diagnose", DiagnoseView.as_view(), name="diagnose"),
    path("diagnose/fix", DiagnoseFixView.as_view(), name="diagnose-fix"),
    path("providers/status", ProviderStatusView.as_view(), name="provider-status"),
    path("audit", AuditView.as_view(), name="audit"),
    path("audit/export", AuditExportView.as_view(), name="audit-export"),
]
