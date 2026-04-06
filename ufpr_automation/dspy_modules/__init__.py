"""DSPy modules for programmatic prompt optimization.

Provides declarative Signatures and compiled Modules that replace
hand-written prompts with optimizable, data-driven prompts.

Usage:
    from ufpr_automation.dspy_modules.modules import EmailClassifierModule
    module = EmailClassifierModule()
    result = module(email_subject="...", email_body="...", rag_context="...")
"""
