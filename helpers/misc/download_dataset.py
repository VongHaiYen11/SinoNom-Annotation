import kagglehub

# Download latest version
path = kagglehub.dataset_download("dmitriigluzdov/vqcc-femoco-public-factorization")

print("Path to dataset files:", path)