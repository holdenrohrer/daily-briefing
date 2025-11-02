from __future__ import annotations

import email
from email import policy
from email.parser import BytesParser
from typing import Any, Dict

from tools.util import llm, escape_sile, sile_img_from_url


async def oneline(email_data: Dict[str, Any]) -> str:
    """
    Filter email to a single line summary for marketing/appointment emails.
    """
    context = f"Subject: {email_data.get('subject', '')}, From: {email_data.get('from', '')}"
    body = email_data.get('raw_body', '')
    
    prompt = (
        "You are a filter. You take an email and pare it down to ONLY ONE SENTENCE. "
        "Marketing emails should become a brief summary. "
        "Appointments should mention the key details in one sentence. "
        "DO NOT INCLUDE EXTRANEOUS FACTS ABOUT THE EMAIL LIKE UNSUBSCRIBE LINKS. "
        f"Note: I already have access to context '{context}'. Do not duplicate the context."
    )
    
    result = await llm(
        system_prompt=prompt,
        user_prompt=body[:10000],  # Limit body length
        return_json=False
    )
    
    return escape_sile(result)


async def verbatim(email_data: Dict[str, Any]) -> str:
    """
    Return email content verbatim with minimal formatting, allowing safe SILE commands.
    """
    body = email_data.get('raw_body', '')
    
    prompt = (
        "You are a filter that preserves important content verbatim. "
        "For personal messages, quotes, and important communications, return the content "
        "with minimal changes but clean formatting. "
        "Use fancy quotation marks to indicate verbatim content when appropriate. "
        "Remove signatures, disclaimers, and unsubscribe links."
    )
    
    result = await llm(
        system_prompt=prompt,
        user_prompt=body[:20000],
        return_json=False
    )
    
    # Allow basic formatting commands but escape everything else
    safe_commands = ['font', 'par', 'smallskip', 'bigskip']
    return escape_sile(result, safe_commands)


async def verbatim_with_images(email_data: Dict[str, Any]) -> str:
    """
    Return email content verbatim with images from URLs and attachments processed.
    """
    body = email_data.get('raw_body', '')
    raw_email = email_data.get('raw_email_bytes', b'')
    
    # Extract images from email attachments
    image_commands = []
    if raw_email:
        image_commands = await _extract_email_images(raw_email)
    
    prompt = (
        "You are a filter that preserves content verbatim while identifying image URLs. "
        "For any image URLs you find in the text, replace them with the placeholder: "
        "{{IMG_URL: <url>}} "
        "Preserve the rest of the content with minimal changes. "
        "Remove signatures, disclaimers, and unsubscribe links. "
        "Use fancy quotation marks for quoted content."
    )
    
    result = await llm(
        system_prompt=prompt,
        user_prompt=body[:20000],
        return_json=False
    )
    
    # Process image URL placeholders
    import re
    def replace_img_url(match):
        url = match.group(1)
        try:
            return sile_img_from_url(url, max_width_in=5.0, max_height_in=4.0)
        except Exception:
            return f"[Image: {url}]"
    
    result = re.sub(r'\{\{IMG_URL:\s*([^}]+)\}\}', replace_img_url, result)
    
    # Add attachment images
    if image_commands:
        result += "\n\n" + "\n".join(image_commands)
    
    # Allow image and formatting commands
    safe_commands = ['img', 'font', 'par', 'smallskip', 'bigskip']
    return escape_sile(result, safe_commands)


async def categorize_email(email_data: Dict[str, Any], valid_categories: list[str]) -> str:
    """
    Use LLM to categorize an email based on its content.
    """
    subject = email_data.get('subject', '')
    from_addr = email_data.get('from', '')
    body = email_data.get('raw_body', '')[:5000]  # Limit for categorization
    
    categories_list = ', '.join(valid_categories)
    
    prompt = (
        f"You are an email categorizer. Based on the email content, "
        f"determine which category this email belongs to from these options: {categories_list}. "
        f"You MUST respond with exactly one of these category names, nothing else: {categories_list}"
    )
    
    user_prompt = f"Subject: {subject}\nFrom: {from_addr}\n\n{body}"
    
    result = await llm(
        system_prompt=prompt,
        user_prompt=user_prompt,
        return_json=False
    )
    
    return result.strip()


async def _extract_email_images(raw_email_bytes: bytes) -> list[str]:
    """
    Extract image attachments from email and convert to SILE image commands.
    """
    try:
        msg = BytesParser(policy=policy.default).parsebytes(raw_email_bytes)
        image_commands = []
        
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition", ""))
                
                if content_type.startswith('image/') and "attachment" in content_disposition:
                    # Extract image data
                    payload = part.get_payload(decode=True)
                    if payload:
                        # Save to temporary file and create SILE command
                        import tempfile
                        import os
                        from pathlib import Path
                        from PIL import Image
                        from tools.util import build_sile_image_from_local
                        
                        # Create temp file with proper extension
                        suffix = '.png'
                        if 'jpeg' in content_type or 'jpg' in content_type:
                            suffix = '.jpg'
                        
                        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f:
                            f.write(payload)
                            temp_path = f.name
                        
                        try:
                            # Convert to PNG if needed
                            if not temp_path.endswith('.png'):
                                png_path = temp_path.rsplit('.', 1)[0] + '.png'
                                with Image.open(temp_path) as img:
                                    if img.mode not in ('RGB', 'RGBA'):
                                        img = img.convert('RGBA')
                                    img.save(png_path, 'PNG')
                                os.unlink(temp_path)
                                temp_path = png_path
                            
                            # Generate SILE command
                            sile_cmd = build_sile_image_from_local(
                                temp_path, 
                                max_width_in=5.0, 
                                max_height_in=4.0
                            )
                            image_commands.append(sile_cmd)
                            
                        except Exception:
                            # Clean up and skip this image
                            if os.path.exists(temp_path):
                                os.unlink(temp_path)
                            continue
        
        return image_commands
        
    except Exception:
        return []