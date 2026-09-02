def format_schema(schema_row):
    return (
        f"{schema_row['Schema (values (type))']}\n"
        f"Primary Keys: {schema_row['Primary Keys']}\n"
        f"Foreign Keys: {schema_row['Foreign Keys']}"
    )

def generate_sql(model, tokenizer, question, db_id, schema_lookup, do_sample=False, temperature=1.0):
    schema_row = schema_lookup[db_id]
    schema_str = format_schema(schema_row)

    prompt = f"Schema:\n{schema_str}\n\nQuestion: {question}\nSQL:"

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