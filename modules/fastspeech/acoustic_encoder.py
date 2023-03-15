import torch
import torch.nn as nn
from torch.nn import functional as F

from modules.commons.common_layers import Embedding, Linear
from modules.fastspeech.tts_modules import FastSpeech2Encoder, mel2ph_to_dur
from utils.hparams import hparams
from utils.pitch_utils import f0_to_coarse
from utils.text_encoder import PAD_INDEX


class FastSpeech2AcousticEncoder(FastSpeech2Encoder):
    def forward_embedding(self, txt_tokens, dur_embed):
        # embed tokens and positions
        x = self.embed_scale * self.embed_tokens(txt_tokens)
        x = x + dur_embed
        if hparams['use_pos_embed']:
            if hparams.get('rel_pos', False):
                x = self.embed_positions(x)
            else:
                positions = self.embed_positions(txt_tokens)
                x = x + positions
        x = F.dropout(x, p=self.dropout, training=self.training)
        return x

    def forward(self, txt_tokens, dur_embed):
        """
        :param txt_tokens: [B, T]
        :param dur_embed: [B, T, H]
        :return: {
            'encoder_out': [T x B x H]
        }
        """
        encoder_padding_mask = txt_tokens.eq(self.padding_idx).detach()
        x = self.forward_embedding(txt_tokens, dur_embed)  # [B, T, H]
        x = super()._forward(x, encoder_padding_mask)
        return x

class FastSpeech2Acoustic(nn.Module):
    def __init__(self, vocab_size):
        super().__init__()
        self.txt_embed = Embedding(vocab_size, hparams['hidden_size'], PAD_INDEX)
        self.dur_embed = Linear(1, hparams['hidden_size'])
        self.encoder = FastSpeech2AcousticEncoder(
            self.txt_embed, hidden_size=hparams['hidden_size'], num_layers=hparams['enc_layers'],
            ffn_kernel_size=hparams['enc_ffn_kernel_size'], num_heads=hparams['num_heads']
        )

        self.f0_embed_type = hparams.get('f0_embed_type', 'discrete')
        if self.f0_embed_type == 'discrete':
            self.pitch_embed = Embedding(300, hparams['hidden_size'], PAD_INDEX)
        elif self.f0_embed_type == 'continuous':
            self.pitch_embed = Linear(1, hparams['hidden_size'])
        else:
            raise ValueError('f0_embed_type must be \'discrete\' or \'continuous\'.')

        if hparams.get('use_key_shift_embed', False):
            self.key_shift_embed = Linear(1, hparams['hidden_size'])

        if hparams.get('use_speed_embed', False):
            self.speed_embed = Linear(1, hparams['hidden_size'])

        if hparams['use_spk_id']:
            self.spk_embed = Embedding(hparams['num_spk'], hparams['hidden_size'])
    
    def forward(self, txt_tokens, mel2ph=None, f0=None, spk_embed_id=None, infer=False, **kwargs):
        B, T = txt_tokens.shape
        dur = mel2ph_to_dur(mel2ph, T).float()
        dur_embed = self.dur_embed(dur[:, :, None])
        encoder_out = self.encoder(txt_tokens, dur_embed)
        
        encoder_out = F.pad(encoder_out, [0, 0, 1, 0])
        mel2ph_ = mel2ph[..., None].repeat([1, 1, encoder_out.shape[-1]])
        condition = torch.gather(encoder_out, 1, mel2ph_)

        nframes = mel2ph.size(1)
        delta_l = nframes - f0.size(1)
        if delta_l > 0:
            f0 = torch.cat((f0,torch.FloatTensor([[x[-1]] * delta_l for x in f0]).to(f0.device)),1)
        f0 = f0[:, :nframes]
        
        if self.f0_embed_type == 'discrete':
            pitch = f0_to_coarse(f0)
            pitch_embed = self.pitch_embed(pitch)
        else:
            f0_mel = (1 + f0 / 700).log()
            pitch_embed = self.pitch_embed(f0_mel[:, :, None])
        condition += pitch_embed

        if hparams.get('use_key_shift_embed', False):
            key_shift = kwargs['key_shift']
            if len(key_shift.shape) == 1:
                key_shift_embed = self.key_shift_embed(key_shift[:, None, None])
            else:
                delta_l = nframes - key_shift.size(1)
                if delta_l > 0:
                    key_shift = torch.cat((key_shift, torch.FloatTensor([[x[-1]] * delta_l for x in key_shift]).to(key_shift.device)), 1)
                key_shift = key_shift[:, :nframes]
                key_shift_embed = self.key_shift_embed(key_shift[:, :, None])
            condition += key_shift_embed

        if hparams.get('use_speed_embed', False):
            speed = kwargs['speed']
            if len(speed.shape) == 1:
                speed_embed = self.speed_embed(speed[:, None, None])
            else:
                delta_l = nframes - speed.size(1)
                if delta_l > 0:
                    speed = torch.cat((speed, torch.FloatTensor([[x[-1]] * delta_l for x in speed]).to(speed.device)), 1)
                speed = speed[:, :nframes]
                speed_embed = self.speed_embed(speed[:, :, None])
            condition += speed_embed

        if hparams['use_spk_id']:
            spk_mix_embed = kwargs.get('spk_mix_embed')
            if spk_mix_embed is not None:
                spk_embed = spk_mix_embed
                mix_frames = spk_embed.size(1)
                if mix_frames > nframes:
                    spk_embed = spk_embed[:, :nframes, :]
                elif mix_frames > 1:
                    spk_embed = torch.cat((spk_embed, spk_embed[:, -1:, :].repeat(1, nframes - mix_frames, 1)), dim=1)
            else:
                spk_embed = self.spk_embed(spk_embed_id)[:, None, :]
            condition += spk_embed

        return condition