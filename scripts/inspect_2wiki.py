from datasets import load_dataset
import pandas as pd

def inspect_dataset():
    dataset_name = "framolfese/2WikiMultihopQA"
    print(f"Downloading and loading dataset: {dataset_name}...")
    
    try:
        # Load the dataset
        dataset = load_dataset(dataset_name)
        
        print("\n--- Dataset Splits ---")
        for split in dataset.keys():
            print(f"- {split}: {len(dataset[split])} examples")
            
        print("\n--- Features/Types ---")
        # Inspect features of the train split (assuming all splits have same features)
        features = dataset['train'].features
        for name, feature in features.items():
            print(f"- {name}: {feature}")
            
        print("\n--- Sample Example (Train) ---")
        print(dataset['train'][0])

        print("\n--- Unique Task Types (from Train) ---")
        unique_types = set(dataset['train']['type'])
        print(unique_types)

    except Exception as e:
        print(f"Error loading dataset: {e}")

if __name__ == "__main__":
    inspect_dataset()
