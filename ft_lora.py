import torch

from unsloth import FastLanguageModel 
from unsloth.chat_templates import standardize_sharegpt, get_chat_template

from trl import SFTTrainer
from transformers import TrainingArguments, DataCollatorForSeq2Seq
from unsloth import is_bfloat16_supported

from unsloth.chat_templates import train_on_responses_only
from datasets import load_dataset
import argparse

max_seq_length = 2048  
load_in_4bit = True

def load_model(model_path, chat_template, r=64, lora_alpha=128, peft_path=None):
    model, tokenizer = FastLanguageModel.from_pretrained(model_name = model_path,
        max_seq_length = max_seq_length,
        load_in_4bit = load_in_4bit,
        # token = hf_
        )

    model = FastLanguageModel.get_peft_model(model,
        r = r, 
        target_modules = ["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj",],
        lora_alpha = lora_alpha,
        lora_dropout = 0, 
        bias = "none",
        use_gradient_checkpointing = "unsloth",
        random_state = 3407
        )

    tokenizer = get_chat_template(tokenizer, chat_template = chat_template)
    return model, tokenizer


def prep_dataset(dataset, tokenizer):
    print(dataset)
    def formatting_prompts_func(examples):
        convos = examples['conversations']
        texts = [
            tokenizer.apply_chat_template(
                convo, tokenize = False, add_generation_prompt = False
            )
            for convo in convos
        ]
        return { "text" : texts, }

    
    dataset = dataset.map(
        formatting_prompts_func,
        batched=True)
    return dataset

from arithmetic.query import templatize, answer
import json
def get_dataset(base):
    data_file = f'ft_data/data_ft_{base}.txt'
    x = [line.strip() for line in open(data_file)][:200]
    y = [answer(line, base) for line in x]
    x = [templatize(line, base) for line in x]
    with open('tmp.json', 'w') as f:
        json.dump([{"conversations":[{'role':'user','content':q},{'role':'assistant','content':a}]} for q,a in zip(x,y)], f)
    dataset = load_dataset('json', data_files='tmp.json')
    return dataset


def train_model(model, tokenizer, base, res_only=True):
    dataset = get_dataset(base)
    dataset = prep_dataset(dataset, tokenizer)
   

    name = f"test_run_{base}"  # Define name here where it's used
    trainer = SFTTrainer(
        model = model,
        tokenizer = tokenizer,
        train_dataset = dataset['train'],
        dataset_text_field = "text",
        max_seq_length = max_seq_length,
        data_collator = DataCollatorForSeq2Seq(tokenizer = tokenizer),
        dataset_num_proc = 2,
        packing = False,
        args = TrainingArguments(
            per_device_train_batch_size = 2,
            gradient_accumulation_steps = 4,
            warmup_steps = 5,
            num_train_epochs = 1, 
            learning_rate = 1e-4,
            fp16 = not is_bfloat16_supported(),
            bf16 = is_bfloat16_supported(),
            logging_steps = 1,
            optim = "adamw_8bit",
            weight_decay = 0.01,
            lr_scheduler_type = "linear",
            seed = 3407,
            output_dir = "outputs/" + name,
            save_strategy = "steps",
            save_steps = 5
        ),
    )

    if res_only:
        trainer = train_on_responses_only(trainer,
        instruction_part="<|im_start|>user<|im_sep|>",
        response_part="<|im_start|>assistant<|im_sep|>")
    
    trainer_stats = trainer.train()
    return trainer_stats


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", type=int, default=10)
    parser.add_argument("--model_path", type=str, default="unsloth/Phi-4")
    args = parser.parse_args()
    
    base = args.base
    model_path = args.model_path
    chat_template = "phi-4"
    r, lora_alpha = 64, 128

    model, tokenizer = load_model(model_path, chat_template, r, lora_alpha)
    print("training model...")
    train_stats = train_model(model, tokenizer, base, res_only=True)
    print(train_stats)

if __name__ == "__main__":
    main()

