SEMANTIC_TERMS = {
  "concert_singer": {
    "high performer": "Age < 30 AND country = 'France'",
  }
}

def find_relevant_terms(question, db_id):
  """
    Checking which known business terms appear in the question.
  """
  terms_for_db = SEMANTIC_TERMS.get(db_id, {})
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