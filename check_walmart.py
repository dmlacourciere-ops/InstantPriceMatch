# Save this as check_walmart.py in your project root
import os

# Check what's in your walmart_playwright.py file
walmart_file = os.path.join("providers", "walmart_playwright.py")

if os.path.exists(walmart_file):
    print("Found walmart_playwright.py!")
    print("Contents:")
    print("="*50)
    
    with open(walmart_file, 'r', encoding='utf-8') as f:
        content = f.read()
        print(content)
        
    print("="*50)
    
    # Look for function definitions
    lines = content.split('\n')
    functions = []
    for i, line in enumerate(lines, 1):
        if line.strip().startswith('def '):
            func_name = line.strip().split('(')[0].replace('def ', '')
            functions.append(f"Line {i}: {func_name}")
    
    if functions:
        print("\nFound these functions:")
        for func in functions:
            print(f"  - {func}")
    else:
        print("\nNo functions found starting with 'def'")
        
else:
    print(f"walmart_playwright.py not found at: {walmart_file}")
    print("Files in providers directory:")
    if os.path.exists("providers"):
        for file in os.listdir("providers"):
            print(f"  - {file}")
    else:
        print("providers directory doesn't exist!")