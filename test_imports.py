# File: test_imports.py
def test_all_modules_import_cleanly():
    import schema_validation
    import db_runner
    import model_utils
    import inference
    # if we get here without an exception, nothing at module level
    # requires a GPU, a loaded model, or network access