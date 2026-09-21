@echo off
setlocal EnableExtensions DisableDelayedExpansion
set "ROOT=%CD%"
set "FAILURES=0"

call :preflight
if errorlevel 1 goto :fatal
call :set_manager_security
if errorlevel 1 goto :fatal

:menu
cls
echo ============================================================
echo  AI1 Model Grabber - choose a template tile
echo ============================================================
echo  1. Krea 2 Extended - Approx. 25.4 GB
echo  2. WAN Motion Control - Approx. 45.4 GB
echo  3. Motion Control GOD Edition - Approx. 61.3 GB
echo  4. MiniMax H3 - Approx. 63.4 GB
echo  A. All tiles
echo  Q. Quit
echo.
set "CHOICE="
set /p "CHOICE=Selection: "
if /i "%CHOICE%"=="1" (set "SELECTED=krea-2-extended"& goto :selected)
if /i "%CHOICE%"=="2" (set "SELECTED=motion-control"& goto :selected)
if /i "%CHOICE%"=="3" (set "SELECTED=motion-control-god-edition"& goto :selected)
if /i "%CHOICE%"=="4" (set "SELECTED=minimax-h3"& goto :selected)
if /i "%CHOICE%"=="A" (set "SELECTED=all"& goto :selected)
if /i "%CHOICE%"=="Q" exit /b 0
echo Invalid selection.
pause
goto :menu

:selected
set "FAILURES=0"

if /i "%SELECTED%"=="krea-2-extended" call :tile_krea-2-extended
if /i "%SELECTED%"=="motion-control" call :tile_motion-control
if /i "%SELECTED%"=="motion-control-god-edition" call :tile_motion-control-god-edition
if /i "%SELECTED%"=="minimax-h3" call :tile_minimax-h3
if /i "%SELECTED%"=="all" call :tile_krea-2-extended
if /i "%SELECTED%"=="all" call :tile_motion-control
if /i "%SELECTED%"=="all" call :tile_minimax-h3
if /i "%SELECTED%"=="all" call :tile_motion-control-god-edition

echo.
if not "%FAILURES%"=="0" goto :partial_failure
echo ============================================================
echo  All selected models and custom nodes are installed.
echo ============================================================
echo Restart ComfyUI before loading the workflow.
echo.
pause
exit /b 0

:tile_krea-2-extended
echo.
echo ============================================================
echo  Krea 2 Extended - Approx. 25.4 GB
echo ============================================================
call :download "https://huggingface.co/Comfy-Org/Krea-2/resolve/main/diffusion_models/krea2_turbo_fp8_scaled.safetensors" "models\diffusion_models\krea2_turbo_fp8_scaled.safetensors" "eb4dd8c612cfd10f64f25b057e6e6bbcb5737c94a7372177e456dbf7579502f1" "none"
if errorlevel 1 set /a FAILURES+=1
call :download "https://huggingface.co/conradlocke/krea2-identity-edit/resolve/main/krea2_identity_edit_v1_2.safetensors" "models\loras\krea2_identity_edit_v1_2.safetensors" "6adf9a69cc9502d286db7b69964d37da7e9cfe4b05b4d004bc275f087d3fd3cf" "none"
if errorlevel 1 set /a FAILURES+=1
call :download "https://huggingface.co/gravedigga/loras/resolve/main/snofs_krea_v1_4.safetensors" "models\loras\snofs_krea_v1_4.safetensors" "767888edde83003f14cf930f13f174fe2a7431e252a515ddf04bd93d382a8932" "none"
if errorlevel 1 set /a FAILURES+=1
call :download "https://huggingface.co/gravedigga/loras/resolve/main/krea2-bloomgirls-realism-step00004000.safetensors" "models\loras\krea2-bloomgirls-realism-step00004000.safetensors" "7ff5ed79d0350c7360b1861829257cbd82b7ca0a75adb97c8716dd1327516c72" "none"
if errorlevel 1 set /a FAILURES+=1
call :download "https://huggingface.co/gravedigga/loras/resolve/main/ass_v2_krea2_loraholic.safetensors" "models\loras\ass_v2_krea2_loraholic.safetensors" "06be93ed343ba85622819f931015c9c6910034cef81208c308fba03590e7ae42" "none"
if errorlevel 1 set /a FAILURES+=1
call :download "https://huggingface.co/gravedigga/loras/resolve/main/breast_size_v2_krea2_loraholic.safetensors" "models\loras\breast_size_v2_krea2_loraholic.safetensors" "24c2acd5d3bf88920a084984099928c85ed17c985d914b8ceb19a1731aafd07f" "none"
if errorlevel 1 set /a FAILURES+=1
call :download "https://huggingface.co/gravedigga/loras/resolve/main/famegrid_spicy.safetensors" "models\loras\famegrid_spicy.safetensors" "7b4a37a9b9ec3885bf39242f2d4f691f186d959cbaaa30b0630e4631767b425e" "none"
if errorlevel 1 set /a FAILURES+=1
call :download "https://huggingface.co/gravedigga/loras/resolve/main/4xNMKDSuperscale_4xNMKDSuperscale.pt" "models\upscale_models\4xNMKDSuperscale_4xNMKDSuperscale.pt" "1d1b0078fe71446e0469d8d4df59e96baa80d83cda600d68237d655830821bcc" "none"
if errorlevel 1 set /a FAILURES+=1
call :download "https://huggingface.co/hfmaster/models-moved/resolve/5b31b4d168315702592e8ee1130c9b794ca22b1c/qwen3vl/Qwen-3-VL-4B-Scaled-FP8.safetensors" "models\text_encoders\qwen3vl_4b_fp8_scaled.safetensors" "35d2897cb1796571616032131f23aabbc85343372cdc7861a560ef3535a4e903" "none"
if errorlevel 1 set /a FAILURES+=1
call :download "https://huggingface.co/QuantStack/Qwen-Image-Edit-GGUF/resolve/5cf642dd2b94af2a558ec06a9dde255c673e1fdf/VAE/Qwen_Image-VAE.safetensors" "models\vae\qwen_image_vae.safetensors" "a70580f0213e67967ee9c95f05bb400e8fb08307e017a924bf3441223e023d1f" "none"
if errorlevel 1 set /a FAILURES+=1
call :download "https://huggingface.co/datasets/Gourieff/ReActor/resolve/main/models/sams/sam_vit_b_01ec64.pth" "models\sams\sam_vit_b_01ec64.pth" "ec2df62732614e57411cdcf32a23ffdf28910380d03139ee0f4fcbe91eb8c912" "none"
if errorlevel 1 set /a FAILURES+=1
call :download "https://huggingface.co/datasets/Gourieff/ReActor/resolve/main/models/detection/bbox/face_yolov8m.pt" "models\ultralytics\bbox\face_yolov8m.pt" "e3893a92c5c1907136b6cc75404094db767c1e0cfefe1b43e87dad72af2e4c9f" "none"
if errorlevel 1 set /a FAILURES+=1
call :node "comfyui-krea2edit" "https://github.com/lbouaraba/comfyui-krea2edit.git" "86f886dac23013d88996e3a2e99093ba44d322fb" ""
if errorlevel 1 set /a FAILURES+=1
call :node "ComfyUI_Comfyroll_CustomNodes" "https://github.com/Suzie1/ComfyUI_Comfyroll_CustomNodes.git" "d78b780ae43fcf8c6b7c6505e6ffb4584281ceca" ""
if errorlevel 1 set /a FAILURES+=1
call :node "ComfyUI-KJNodes" "https://github.com/kijai/ComfyUI-KJNodes.git" "8692bc8ef8beaaeee80fd52ba80477dc9e61547b" ""
if errorlevel 1 set /a FAILURES+=1
call :node "ComfyUI-Impact-Subpack" "https://github.com/ltdrdata/ComfyUI-Impact-Subpack.git" "50c7b71a6a224734cc9b21963c6d1926816a97f1" ""
if errorlevel 1 set /a FAILURES+=1
call :node "ComfyUI-Impact-Pack" "https://github.com/ltdrdata/ComfyUI-Impact-Pack.git" "429d0159ad429e64d2b3916e6e7be9c22d025c3c" ""
if errorlevel 1 set /a FAILURES+=1
call :node "rgthree-comfy" "https://github.com/rgthree/rgthree-comfy.git" "6b76ee6f2c5a007710b5a16f97c94330d6ecc871" ""
if errorlevel 1 set /a FAILURES+=1
call :node "RES4LYF" "https://github.com/ClownsharkBatwing/RES4LYF.git" "e716cd1cb2c5cff90131bf4914b75b75a0489d48" ""
if errorlevel 1 set /a FAILURES+=1
exit /b 0

:tile_motion-control
echo.
echo ============================================================
echo  WAN Motion Control - Approx. 45.4 GB
echo ============================================================
call :download "https://huggingface.co/Comfy-Org/sam3.1/resolve/main/checkpoints/sam3.1_multiplex_fp16.safetensors" "models\checkpoints\sam3.1_multiplex_fp16.safetensors" "9ba99c92703c2e8b4f47de2d34a539bb8e18923049e238b780d70dbe6368eb03" "none"
if errorlevel 1 set /a FAILURES+=1
call :download "https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged/resolve/main/split_files/clip_vision/clip_vision_h.safetensors" "models\clip_vision\clip_vision_h.safetensors" "64a7ef761bfccbadbaa3da77366aac4185a6c58fa5de5f589b42a65bcc21f161" "none"
if errorlevel 1 set /a FAILURES+=1
call :download "https://huggingface.co/Comfy-Org/SCAIL-2/resolve/main/diffusion_models/wan2.1_14B_SCAIL_2_fp16.safetensors" "models\diffusion_models\wan2.1_14B_SCAIL_2_fp16.safetensors" "e3f9cd52184949ee8ffdc01ba14de4c619e0ddfa09ae105cb7efce5c8dc9fe43" "none"
if errorlevel 1 set /a FAILURES+=1
call :download "https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged/resolve/main/split_files/vae/wan_2.1_vae.safetensors" "models\vae\wan_2.1_vae.safetensors" "2fc39d31359a4b0a64f55876d8ff7fa8d780956ae2cb13463b0223e15148976b" "none"
if errorlevel 1 set /a FAILURES+=1
call :download "https://huggingface.co/lightx2v/Wan2.2-Distill-Loras/resolve/9ff6e8a86c2fcc7548256555ba274ecec69fefff/wan2.2_i2v_A14b_low_noise_lora_rank64_lightx2v_4step_1022.safetensors" "models\loras\wan2.2_i2v_A14b_low_noise_lora_rank64_lightx2v_4step_1022.safetensors" "8833bd4fd7c8eabebf0bc8ee5cfaf47f4f310ce116928a02c1adf8941dd4b0f1" "none"
if errorlevel 1 set /a FAILURES+=1
call :download "https://huggingface.co/gravedigga/loras/resolve/main/slop_twerk_LowNoise_merged3_7_v2.safetensors" "models\loras\slop_twerk_LowNoise_merged3_7_v2.safetensors" "d70d23144d43ee6d7ffbd3d2d5cade1f0f9004a3e013a7c33dd2f91f37e438ea" "none"
if errorlevel 1 set /a FAILURES+=1
call :download "https://huggingface.co/gravedigga/loras/resolve/main/slop_twerk_HighNoise_merged3_7_v2.safetensors" "models\loras\slop_twerk_HighNoise_merged3_7_v2.safetensors" "83fe88476f551aa0acdd119c6993de30910139b1635dc08c7f986fc3459d7cc5" "none"
if errorlevel 1 set /a FAILURES+=1
call :download "https://huggingface.co/Comfy-Org/SCAIL-2/resolve/main/loras/wan2.1_SCAIL_2_DPO_lora_bf16.safetensors" "models\loras\wan2.1_SCAIL_2_DPO_lora_bf16.safetensors" "b106522036f64e50f5f8ae3b808973515ff442cc2fac27b65d875eafb95b89e2" "none"
if errorlevel 1 set /a FAILURES+=1
call :download "https://huggingface.co/UmeAiRT/ComfyUI-Auto-Installer-Assets/resolve/refs%%%%2Fpr%%%%2F5/models/clip/umt5-xxl-encoder-fp8-e4m3fn-scaled.safetensors" "models\text_encoders\umt5-xxl-encoder-fp8-e4m3fn-scaled.safetensors" "c3355d30191f1f066b26d93fba017ae9809dce6c627dda5f6a66eaa651204f68" "none"
if errorlevel 1 set /a FAILURES+=1
call :node "ComfyUI-SAM3" "https://github.com/PozzettiAndrea/ComfyUI-SAM3.git" "de0ff5d2c2ea435d29f800abfa568cffdfb94773" ""
if errorlevel 1 set /a FAILURES+=1
call :node "ComfyUI-VideoHelperSuite" "https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite.git" "4ee72c065db22c9d96c2427954dc69e7b908444b" ""
if errorlevel 1 set /a FAILURES+=1
call :node "ComfyUI-Logic" "https://github.com/theUpsider/ComfyUI-Logic.git" "ae0ca532177eef7325d207f8b8a2f88f4d1a837c" ""
if errorlevel 1 set /a FAILURES+=1
call :node "Nvidia_RTX_Nodes_ComfyUI" "https://github.com/Comfy-Org/Nvidia_RTX_Nodes_ComfyUI.git" "892515e3eb9a4920a131a502a047e47adca9eb0d" "https://pypi.nvidia.com/"
if errorlevel 1 set /a FAILURES+=1
call :node "ComfyUI-Easy-Use" "https://github.com/yolain/ComfyUI-Easy-Use.git" "271685698b0935c5b0ecca86a58c3817931cd205" ""
if errorlevel 1 set /a FAILURES+=1
call :node "ComfyUI-Custom-Scripts" "https://github.com/pythongosssss/ComfyUI-Custom-Scripts.git" "609f3afaa74b2f88ef9ce8d939626065e3247469" ""
if errorlevel 1 set /a FAILURES+=1
call :node "ComfyUI-Impact-Pack" "https://github.com/ltdrdata/ComfyUI-Impact-Pack.git" "429d0159ad429e64d2b3916e6e7be9c22d025c3c" ""
if errorlevel 1 set /a FAILURES+=1
exit /b 0

:tile_motion-control-god-edition
echo.
echo ============================================================
echo  Motion Control GOD Edition - Approx. 61.3 GB
echo ============================================================
call :download "https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/resolve/main/split_files/diffusion_models/wan2.2_animate_14B_bf16.safetensors" "models\diffusion_models\wan2.2_animate_14B_bf16.safetensors" "7d37cb0120488dec2a061135aa3018426925318a60838c3de935c829abc88667" "none"
if errorlevel 1 set /a FAILURES+=1
call :download "https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/resolve/main/split_files/loras/wan2.2_animate_14B_relight_lora_bf16.safetensors" "models\loras\wan2.2_animate_14B_relight_lora_bf16.safetensors" "5f4b6b9d3bc745a86e7bfd511f3880d90cf59c3bded9584d92c028f583fa74a3" "none"
if errorlevel 1 set /a FAILURES+=1
call :download "https://huggingface.co/Kijai/WanVideo_comfy/resolve/main/Lightx2v/lightx2v_T2V_14B_cfg_step_distill_v2_lora_rank256_bf16.safetensors" "models\loras\lightx2v_T2V_14B_cfg_step_distill_v2_lora_rank256_bf16.safetensors" "0bda20598ece84b0b2f2385204e1f2e32b1fd2e2648662021be832fe1f227fab" "none"
if errorlevel 1 set /a FAILURES+=1
call :download "https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/resolve/main/split_files/loras/wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors" "models\loras\wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors" "024f21de095bc8fad9809ded3e9e49a2e170dcf27075da8145ba7d60d8aab7f9" "none"
if errorlevel 1 set /a FAILURES+=1
call :download "https://huggingface.co/Kijai/WanVideo_comfy/resolve/main/Pusa/Wan21_PusaV1_LoRA_14B_rank512_bf16.safetensors" "models\loras\Wan21_PusaV1_LoRA_14B_rank512_bf16.safetensors" "a510b5562e05efa831127bd6a6b3aecf1c4747cffdddcc0b28f88c0667ef1694" "none"
if errorlevel 1 set /a FAILURES+=1
call :download "https://huggingface.co/smegmarip/ComfyUI/resolve/main/loras/Wan2.2-Fun-A14B-InP-low-noise-MPS.safetensors" "models\loras\Wan2.2-Fun-A14B-InP-low-noise-MPS.safetensors" "0e6ac56c89068386b002b18ab4542207e2c0c431f3c4ac367ae64fece85dd680" "none"
if errorlevel 1 set /a FAILURES+=1
call :download "https://huggingface.co/Kijai/WanVideo_comfy/resolve/main/Wan2_1_VAE_bf16.safetensors" "models\vae\Wan2_1_VAE_bf16.safetensors" "1ab9a32cc2c740f6e39d80d367ce5dcc28db8c71b79b28670546b8973e9d75f9" "none"
if errorlevel 1 set /a FAILURES+=1
call :download "https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged/resolve/main/split_files/text_encoders/umt5_xxl_fp16.safetensors" "models\text_encoders\umt5_xxl_fp16.safetensors" "7b8850f1961e1cf8a77cca4c964a358d303f490833c6c087d0cff4b2f99db2af" "none"
if errorlevel 1 set /a FAILURES+=1
call :download "https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged/resolve/main/split_files/clip_vision/clip_vision_h.safetensors" "models\clip_vision\clip_vision_h.safetensors" "64a7ef761bfccbadbaa3da77366aac4185a6c58fa5de5f589b42a65bcc21f161" "none"
if errorlevel 1 set /a FAILURES+=1
call :download "https://huggingface.co/Wan-AI/Wan2.2-Animate-14B/resolve/main/process_checkpoint/det/yolov10m.onnx" "models\detection\yolov10m.onnx" "89b526498a6d55f869a6ab52e3a2eb20ad45b3711c1f7de3dd9ca0b399dfd6d7" "none"
if errorlevel 1 set /a FAILURES+=1
call :download "https://huggingface.co/Kijai/vitpose_comfy/resolve/main/onnx/vitpose_h_wholebody_model.onnx" "models\detection\vitpose_h_wholebody_model.onnx" "f21466cd6c93d0066782ad5923c14a4e6569133def212dc2895c73596c2e553b" "none"
if errorlevel 1 set /a FAILURES+=1
call :download "https://huggingface.co/Kijai/vitpose_comfy/resolve/main/onnx/vitpose_h_wholebody_data.bin" "models\detection\vitpose_h_wholebody_data.bin" "f6a9e7cb3a87ed65a098b096029e70150408acfafc3d695019a66b289d7719e1" "none"
if errorlevel 1 set /a FAILURES+=1
call :download "https://huggingface.co/fofr/comfyui/resolve/main/sam2/sam2.1_hiera_base_plus.safetensors" "models\sams\sam2.1_hiera_base_plus.safetensors" "eb4b5f725c8b68205aa05bbe6b27efc628b18b4b9c7b9bb8218991b86b9a4932" "none"
if errorlevel 1 set /a FAILURES+=1
call :download "https://github.com/Fannovel16/ComfyUI-Frame-Interpolation/releases/download/models/rife49.pth" "models\frame_interpolation\rife49.pth" "e55fd00f3cc184e3c65961f4bb827a9da022e78eed36b055242c0ac30000d533" "none"
if errorlevel 1 set /a FAILURES+=1
call :node "ComfyUI-WanVideoWrapper" "https://github.com/kijai/ComfyUI-WanVideoWrapper.git" "b2c8cf969fcf60a38884ea2c29af177ae1f28b29" ""
if errorlevel 1 set /a FAILURES+=1
call :node "ComfyUI-WanAnimatePreprocess" "https://github.com/kijai/ComfyUI-WanAnimatePreprocess.git" "0e0b6a2a555625acf4d4aefb780e27d06937132f" ""
if errorlevel 1 set /a FAILURES+=1
call :node "ComfyUI-KJNodes" "https://github.com/kijai/ComfyUI-KJNodes.git" "c9869eade9920a1b949de07c4a197156006bcceb" ""
if errorlevel 1 set /a FAILURES+=1
call :node "ComfyUI-segment-anything-2" "https://github.com/kijai/ComfyUI-segment-anything-2.git" "c59676b008a76237002926f684d0ca3a9b29ac54" ""
if errorlevel 1 set /a FAILURES+=1
call :node "ComfyUI-VideoHelperSuite" "https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite.git" "0edce8ef7ce173ac97a3ed3d6f4636029d1a4530" ""
if errorlevel 1 set /a FAILURES+=1
call :node "ComfyUI-Frame-Interpolation" "https://github.com/Fannovel16/ComfyUI-Frame-Interpolation.git" "a969c01dbccd9e5510641be04eb51fe93f6bfc3d" ""
if errorlevel 1 set /a FAILURES+=1
call :node "ComfyUI-Custom-Scripts" "https://github.com/pythongosssss/ComfyUI-Custom-Scripts.git" "aac13aa7ce35b07d43633c3bbe654a38c00d74f5" ""
if errorlevel 1 set /a FAILURES+=1
call :node "rgthree-comfy" "https://github.com/rgthree/rgthree-comfy.git" "eadc24ecc8bfc3c80fcc50724c0ebe74489f255b" ""
if errorlevel 1 set /a FAILURES+=1
call :node "ComfyUI-Easy-Use" "https://github.com/yolain/ComfyUI-Easy-Use.git" "a1b402b4a9c0ddd35c0ac1197579f8f7b121ff3e" ""
if errorlevel 1 set /a FAILURES+=1
call :node "ComfyMath" "https://github.com/evanspearman/ComfyMath.git" "c01177221c31b8e5fbc062778fc8254aeb541638" ""
if errorlevel 1 set /a FAILURES+=1
call :node "comfyui-propost" "https://github.com/digitaljohn/comfyui-propost.git" "df6a6d122498f57ad7195d58e07701a501c9dcb6" ""
if errorlevel 1 set /a FAILURES+=1
call :node "CRT-Nodes" "https://github.com/PGCRT/CRT-Nodes.git" "7e277170b525a07fc4a9b6fd1e87ee00ec9628e4" ""
if errorlevel 1 set /a FAILURES+=1
call :node "ComfyUI_Swwan" "https://github.com/aining2022/ComfyUI_Swwan.git" "7cfbebaf850d1ce8eaa3bda63e10597d8864261d" ""
if errorlevel 1 set /a FAILURES+=1
call :link_model "models\frame_interpolation\rife49.pth" "custom_nodes\ComfyUI-Frame-Interpolation\ckpts\rife\rife49.pth" "e55fd00f3cc184e3c65961f4bb827a9da022e78eed36b055242c0ac30000d533"
if errorlevel 1 set /a FAILURES+=1
exit /b 0

:tile_minimax-h3
echo.
echo ============================================================
echo  MiniMax H3 - Approx. 63.4 GB
echo ============================================================
call :download "https://huggingface.co/Comfy-Org/MiniMax-H3/resolve/main/diffusion_models/minimax_h3_fl2va_pruned_int8_convrot.safetensors" "models\diffusion_models\minimax_h3_fl2va_pruned_int8_convrot.safetensors" "e889202c41dafb67b10d67b97f0d8541508036a6090af23425a5c2615d03c47a" "none"
if errorlevel 1 set /a FAILURES+=1
call :download "https://huggingface.co/Comfy-Org/MiniMax-H3/resolve/main/diffusion_models/minimax_h3_ref2va_pruned_int8_convrot.safetensors" "models\diffusion_models\minimax_h3_ref2va_pruned_int8_convrot.safetensors" "9255f52b6677845ad238f20dfaafa94727053694127ab7f255c048f0f9365779" "none"
if errorlevel 1 set /a FAILURES+=1
call :download "https://huggingface.co/Comfy-Org/MiniMax-H3/resolve/main/text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors" "models\text_encoders\qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors" "35a88d51044231fe332301d7a62aa81e3f2cba62febeb446e2c1e3e0ef76f2c6" "none"
if errorlevel 1 set /a FAILURES+=1
call :download "https://huggingface.co/Comfy-Org/MiniMax-H3/resolve/main/vae/minimax_h3_video_vae_fp16.safetensors" "models\vae\minimax_h3_video_vae_fp16.safetensors" "7c1f131492e7eddacaac9069a61b81bdd39de5cc96561e677c5eab1cdce5e522" "none"
if errorlevel 1 set /a FAILURES+=1
call :download "https://huggingface.co/Comfy-Org/MiniMax-H3/resolve/main/vae/minimax_h3_audio_vae_fp32.safetensors" "models\vae\minimax_h3_audio_vae_fp32.safetensors" "8e505d95dd1561d47abd43d4238fd40d9bb1ae9e147ed0a4cba778d76ae4db48" "none"
if errorlevel 1 set /a FAILURES+=1
call :node "ComfyUI-KJNodes" "https://github.com/kijai/ComfyUI-KJNodes.git" "8692bc8ef8beaaeee80fd52ba80477dc9e61547b" ""
if errorlevel 1 set /a FAILURES+=1
call :node "rgthree-comfy" "https://github.com/rgthree/rgthree-comfy.git" "6b76ee6f2c5a007710b5a16f97c94330d6ecc871" ""
if errorlevel 1 set /a FAILURES+=1
call :node "ComfyUI-VideoHelperSuite" "https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite.git" "4ee72c065db22c9d96c2427954dc69e7b908444b" ""
if errorlevel 1 set /a FAILURES+=1
exit /b 0

:preflight
if not exist "%ROOT%\main.py" (
    echo ERROR: Run this file from the main ComfyUI directory.
    echo        main.py was not found in: %ROOT%
    exit /b 1
)
if not exist "%ROOT%\models" (
    echo ERROR: The ComfyUI models folder was not found in: %ROOT%
    exit /b 1
)
where curl.exe >nul 2>nul || (echo ERROR: curl.exe was not found.& exit /b 1)
where powershell.exe >nul 2>nul || (echo ERROR: Windows PowerShell was not found.& exit /b 1)
where git.exe >nul 2>nul || (echo ERROR: Git was not found.& exit /b 1)
call :find_python
if errorlevel 1 exit /b 1
exit /b 0

:find_python
set "PYTHON="
if exist "%ROOT%\.venv\Scripts\python.exe" set "PYTHON=%ROOT%\.venv\Scripts\python.exe"
if not defined PYTHON if exist "%ROOT%\venv\Scripts\python.exe" set "PYTHON=%ROOT%\venv\Scripts\python.exe"
if not defined PYTHON if exist "%ROOT%\python_embeded\python.exe" set "PYTHON=%ROOT%\python_embeded\python.exe"
if not defined PYTHON if exist "%ROOT%\python_embedded\python.exe" set "PYTHON=%ROOT%\python_embedded\python.exe"
if not defined PYTHON if exist "%ROOT%\..\python_embeded\python.exe" set "PYTHON=%ROOT%\..\python_embeded\python.exe"
if not defined PYTHON if exist "%ROOT%\..\python_embedded\python.exe" set "PYTHON=%ROOT%\..\python_embedded\python.exe"
if not defined PYTHON set "PYTHON=python"
"%PYTHON%" --version >nul 2>nul
if errorlevel 1 (echo ERROR: The Python environment used by ComfyUI was not found.& exit /b 1)
exit /b 0

:set_manager_security
set "MANAGER_CONFIG=%ROOT%\user\__manager\config.ini"
for %%D in ("%MANAGER_CONFIG%") do if not exist "%%~dpD" mkdir "%%~dpD"
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "$path=$env:MANAGER_CONFIG; $lines=if(Test-Path -LiteralPath $path){@(Get-Content -LiteralPath $path)}else{@()}; $section=-1; for($i=0;$i -lt $lines.Count;$i++){if($lines[$i] -match '^\s*\[default\]\s*$'){$section=$i;break}}; if($section -lt 0){if($lines.Count -gt 0 -and $lines[-1] -ne ''){$lines += ''}; $lines += '[default]'; $lines += 'security_level = weak'}else{$found=$false; for($i=$section+1;$i -lt $lines.Count;$i++){if($lines[$i] -match '^\s*\[[^]]+\]\s*$'){break}; if($lines[$i] -match '^\s*security_level\s*='){$lines[$i]='security_level = weak';$found=$true;break}}; if(-not $found){$head=@($lines[0..$section]); $tail=if($section+1 -lt $lines.Count){@($lines[($section+1)..($lines.Count-1)])}else{@()}; $lines=@($head+'security_level = weak'+$tail)}}; [IO.File]::WriteAllLines($path,[string[]]$lines,[Text.UTF8Encoding]::new($false))"
if errorlevel 1 (echo ERROR: Could not set ComfyUI-Manager security_level to weak.& exit /b 1)
echo [OK] ComfyUI-Manager security_level = weak
set "MANAGER_CONFIG="
exit /b 0

:download
set "DL_URL=%~1"
set "DL_DEST=%ROOT%\%~2"
set "DL_SHA=%~3"
set "DL_AUTH=%~4"
for %%D in ("%DL_DEST%") do if not exist "%%~dpD" mkdir "%%~dpD"
if exist "%DL_DEST%" (
    call :verify "%DL_DEST%" "%DL_SHA%"
    if not errorlevel 1 (echo [SKIP] Verified: %~2& exit /b 0)
    echo [RETRY] Existing file failed verification and will be replaced: %~2
    del /q "%DL_DEST%" >nul 2>nul
)
echo [DOWNLOAD] %~2
if /i "%DL_AUTH%"=="huggingface" (
    curl.exe --location --fail --retry 5 --retry-delay 5 --connect-timeout 30 --continue-at - -H "Authorization: Bearer %HF_TOKEN%" --output "%DL_DEST%.part" "%DL_URL%"
) else (
    curl.exe --location --fail --retry 5 --retry-delay 5 --connect-timeout 30 --continue-at - --output "%DL_DEST%.part" "%DL_URL%"
)
if errorlevel 1 (echo [ERROR] Download failed; partial file retained for resume: %~2& exit /b 1)
call :verify "%DL_DEST%.part" "%DL_SHA%"
if errorlevel 1 (
    echo [ERROR] SHA-256 mismatch: %~2
    del /q "%DL_DEST%.part" >nul 2>nul
    exit /b 1
)
move /y "%DL_DEST%.part" "%DL_DEST%" >nul
if errorlevel 1 (echo [ERROR] Could not finalize: %~2& exit /b 1)
echo [OK] %~2
exit /b 0

:verify
set "VERIFY_FILE=%~1"
set "VERIFY_SHA=%~2"
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "Import-Module Microsoft.PowerShell.Utility; $actual=(Get-FileHash -Algorithm SHA256 -LiteralPath $env:VERIFY_FILE).Hash.ToLowerInvariant(); if($actual -ne $env:VERIFY_SHA){exit 1}"
set "VERIFY_RESULT=%ERRORLEVEL%"
set "VERIFY_FILE="
set "VERIFY_SHA="
exit /b %VERIFY_RESULT%

:node
echo [NODE] Preparing: %~1
set "NODE_NAME=%~1"
set "NODE_URL=%~2"
set "NODE_REF=%~3"
set "NODE_EXTRA_INDEX=%~4"
set "NODE_DEST=%ROOT%\custom_nodes\%~1"
if exist "%NODE_DEST%" if not exist "%NODE_DEST%\.git" (echo [ERROR] %NODE_DEST% exists but is not a Git repository.& exit /b 1)
if not exist "%ROOT%\custom_nodes" mkdir "%ROOT%\custom_nodes"
if not exist "%NODE_DEST%\.git" (
    echo [CLONE] %NODE_NAME%
    git.exe clone --filter=blob:none "%NODE_URL%" "%NODE_DEST%"
    if errorlevel 1 (echo [ERROR] Clone failed: %NODE_NAME%& exit /b 1)
)
git.exe -C "%NODE_DEST%" remote set-url origin "%NODE_URL%"
if errorlevel 1 (echo [ERROR] Could not configure: %NODE_NAME%& exit /b 1)
git.exe -C "%NODE_DEST%" cat-file -e "%NODE_REF%^{commit}" >nul 2>nul
if errorlevel 1 git.exe -C "%NODE_DEST%" fetch --no-tags --filter=blob:none origin "%NODE_REF%"
if errorlevel 1 (echo [ERROR] Fetch failed: %NODE_NAME%& exit /b 1)
git.exe -C "%NODE_DEST%" checkout --detach "%NODE_REF%"
if errorlevel 1 (echo [ERROR] Checkout failed: %NODE_NAME%& exit /b 1)
if exist "%NODE_DEST%\requirements.txt" (
    echo [REQUIREMENTS] %NODE_NAME%
    if defined NODE_EXTRA_INDEX (
        "%PYTHON%" -m pip install --disable-pip-version-check --no-build-isolation --extra-index-url "%NODE_EXTRA_INDEX%" -r "%NODE_DEST%\requirements.txt"
    ) else (
        "%PYTHON%" -m pip install --disable-pip-version-check --no-build-isolation -r "%NODE_DEST%\requirements.txt"
    )
    if errorlevel 1 (echo [ERROR] Requirements failed: %NODE_NAME%& exit /b 1)
)
echo [OK] %NODE_NAME%
exit /b 0

:link_model
set "LINK_SOURCE=%ROOT%\%~1"
set "LINK_DEST=%ROOT%\%~2"
set "LINK_SHA=%~3"
if not exist "%LINK_SOURCE%" (echo [ERROR] Link source was not found: %~1& exit /b 1)
if exist "%LINK_DEST%" (
    call :verify "%LINK_DEST%" "%LINK_SHA%"
    if not errorlevel 1 (echo [SKIP] Verified linked model: %~2& exit /b 0)
    echo [ERROR] Existing linked model failed verification: %~2
    exit /b 1
)
for %%D in ("%LINK_DEST%") do if not exist "%%~dpD" mkdir "%%~dpD"
mklink /H "%LINK_DEST%" "%LINK_SOURCE%" >nul 2>nul
if errorlevel 1 copy /y "%LINK_SOURCE%" "%LINK_DEST%" >nul
if errorlevel 1 (echo [ERROR] Could not link or copy model: %~2& exit /b 1)
call :verify "%LINK_DEST%" "%LINK_SHA%"
if errorlevel 1 (echo [ERROR] Linked model failed verification: %~2& exit /b 1)
echo [OK] Linked model: %~2
exit /b 0

:partial_failure
echo ============================================================
echo  Finished with %FAILURES% failed item(s).
echo ============================================================
echo Successful files were retained. Run the script again to retry or resume.
echo.
pause
exit /b 1

:fatal
echo.
echo Installation could not start.
echo.
pause
exit /b 1
