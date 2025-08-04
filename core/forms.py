# core/forms.py

from django import forms
from django.contrib.auth.forms import AuthenticationForm

class CustomAuthenticationForm(AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Aquí personalizamos los campos del formulario
        self.fields['username'].widget.attrs.update({
            'class': 'form-control',
            'placeholder': 'Correo Electrónico'
        })
        self.fields['password'].widget.attrs.update({
            'class': 'form-control',
            'placeholder': 'Contraseña'
        })