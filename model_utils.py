from semantic_layer import inject_semantic_terms

def format_schema(schema_row):
    return (
        f"{schema_row['Schema (values (type))']}\n"
        f"Primary Keys: {schema_row['Primary Keys']}\n"
        f"Foreign Keys: {schema_row['Foreign Keys']}"
    )

def format_live_schema(live_schema):
    """
        Build an equivalent prompt-ready schema string from db_connection.get_live_schema()'s dict.
    """
    lines = []
    pk_lines = []
    fk_lines = []

    for table, info in live_schema.items():
        cols = ", ".join(f"{c['name']} ({c['type']})" for c in info["columns"])
        lines.append(f"{table}: {cols}")

        if info["primary_key"]:
            pk_lines.append(f"{table}: {", ".join(info['primary_key'])}")

        for fk in info["foreign_keys"]:
            fk_lines.append(f"{table}.{", ".join(fk['columns'])} -> {fk['references']}")

    schema_block = " | ".join(lines)
    pk_block = "; ".join(pk_lines)
    fk_block = "; ".join(fk_lines)

    return f"{schema_block}\nPrimary Keys: {pk_block}\nForeign Keys: {fk_block}"
           

def generate_sql(model, tokenizer, question, db_id=None, schema_lookup=None, live_schema=None,do_sample=False, temperature=1.0):
    if live_schema is not None:
       schema_str = format_live_schema(live_schema)
    else:
       if schema_lookup is None or db_id is None:
          raise ValueError("Must provide either live_schema, or both db_id and schema_lookup")   
       schema_row = schema_lookup[db_id]
       schema_str = format_schema(schema_row)

    semantic_context = inject_semantic_terms(question, db_id) if db_id else ""

    prompt = f"Schema:\n{schema_str}\n"
    if semantic_context:    
       prompt += f"\n{semantic_context}\n"
    prompt += f"\nQuestion: {question}\nSQL:"
       
    messages = [{"role": "user", "content": prompt}]
    inputs = tokenizer.apply_chat_template(
        messages, add_generation_prompt=True, return_tensors="pt", return_dict=True
    ).to(model.device)

    gen_kwargs = dict(max_new_tokens=256, pad_token_id=tokenizer.eos_token_id)
    if do_sample:
      gen_kwargs.update(do_sample=True, temperature=temperature, top_p=0.9)
    else:
      gen_kwargs.update(do_sample=False)

    outputs = model.generate(**inputs, **gen_kwargs)
    input_len = inputs["input_ids"].shape[-1]
    text = tokenizer.decode(outputs[0][input_len:], skip_special_tokens=True)
    return text.strip()