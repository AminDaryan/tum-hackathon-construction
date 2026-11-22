"""LLM orchestration (later phase): provider abstraction, schema-validated validation planner.

The LLM may only *select and configure registered detectors* by producing a
:class:`app.models.plan.ValidationPlan`, which passes through the same strict
:class:`app.validation.plan_validation.PlanValidator` as any other plan. It never executes code,
SQL or shell commands. The application is fully functional without any LLM provider.
"""
