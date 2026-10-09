# File: test_imports.py
def test_all_modules_import_cleanly():
    import app.services.schema_validation
    import app.db.runner
    import app.services.model_utils
    import app.services.inference
    # if we get here without an exception, nothing at module level
    # requires a GPU, a loaded model, or network access