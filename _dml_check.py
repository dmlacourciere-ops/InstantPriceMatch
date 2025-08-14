import torch, torch_directml
dml = torch_directml.device()
x = torch.randn(2,3,224,224, device=dml)
print('DirectML device:', x.device)
