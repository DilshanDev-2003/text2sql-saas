import json
import os

SEMANTIC_TERMS_PATH = os.path.join(os.path.dirname(__file__), "semantic_terms.json")

def load_semantic_terms():
  """
    Load Semantic Terms from semantic_terms.json.
  """
  if not os.path.exists(SEMANTIC_TERMS_PATH):
    return {}
  with open(SEMANTIC_TERMS_PATH) as f:
    return json.load(f)

def add_new_term(db_id, term, meaning):
  """
    Add or overwrite new terms for the semantic_terms.json.
  """  
  all_terms = load_semantic_terms()

  if db_id not in all_terms:
    all_terms[db_id] = {}

  all_terms[db_id][term] = meaning

  with open(SEMANTIC_TERMS_PATH, "w") as f:
    json.dump(all_terms, f, indent=2)

def list_terms(db_id):
  """
    List all the terms for a given database.
  """    
  all_terms = load_semantic_terms()
  return all_terms.get(db_id, {})

def remove_terms(db_id, term):
  """
    Remove a term if it exists.
  """
  all_terms = load_semantic_terms()
  if db_id in all_terms and all_terms[db_id]:
    del all_terms[db_id][term]
  with open(SEMANTIC_TERMS_PATH, "w") as f:
    json.dump(all_terms, f, indent=2)

def find_relevant_terms(question, db_id):
  """
    Checking which known business terms appear in the question.
  """
  all_terms = load_semantic_terms()
  terms_for_db = all_terms.get(db_id, {})
  question_lower = question.lower()

  matched = {}

  for term, meaning in terms_for_db.items():
    if term.lower() in question_lower:
      matched[term] = meaning

  return matched   

def inject_semantic_terms(question, db_id):
  """
    Adding semantic terms and meanings to the prompt.
  """ 
  matched = find_relevant_terms(question, db_id)

  if not matched:
    return ""

  lines = ["Business Term Definitions:"]
  for terms, meaning in matched.items():
    lines.append(f'- "{terms}" means: {meaning}')

  return "\n".join(lines)  