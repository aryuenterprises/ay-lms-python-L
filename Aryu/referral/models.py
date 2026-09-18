import re
from django.db import models
from django.contrib.auth.hashers import make_password, check_password, is_password_usable


def generate_coupon_code():
    """
    Generates sequential coupon code in format PASSATS001, PASSATS002, PASSATS003...
    """
    existing_codes = Referral.objects.filter(
        coupon_code__startswith="PASSATS"
    ).values_list("coupon_code", flat=True)

    max_num = 0
    for code in existing_codes:
        match = re.match(r"^PASSATS(\d+)$", code)
        if match:
            try:
                num = int(match.group(1))
                if num > max_num:
                    max_num = num
            except ValueError:
                pass

    next_num = max_num + 1
    new_code = f"PASSATS{next_num:03d}"

    # Ensure uniqueness in case of gaps or concurrent entries
    while Referral.objects.filter(coupon_code=new_code).exists():
        next_num += 1
        new_code = f"PASSATS{next_num:03d}"

    return new_code


class Referral(models.Model):
    STATUS_CHOICES = [
        ("active", "Active"),
        ("inactive", "Inactive"),
    ]

    name = models.CharField(max_length=255)
    email = models.EmailField(unique=True, db_index=True)
    password = models.CharField(max_length=255)
    coupon_code = models.CharField(max_length=50, unique=True, db_index=True, blank=True)
    url = models.CharField(max_length=500, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "referral"
        ordering = ["-created_at"]
        verbose_name = "Referral"
        verbose_name_plural = "Referrals"

    def __str__(self):
        return f"{self.name} ({self.coupon_code}) - {self.status}"

    def set_password(self, raw_password):
        """Hashes raw password and sets to self.password."""
        if raw_password:
            self.password = make_password(raw_password)

    def check_password(self, raw_password):
        """Checks raw password against hashed password."""
        if not self.password:
            return False
        return check_password(raw_password, self.password)

    def save(self, *args, **kwargs):
        # Auto-generate coupon code if not set
        if not self.coupon_code:
            self.coupon_code = generate_coupon_code()

        # Auto-generate url using coupon code if not set
        if not self.url and self.coupon_code:
            self.url = f"https://passats.aryuacademy.com/{self.coupon_code}"

        # Hash password if raw string (not already hashed)
        if self.password:
            # Check if already hashed
            # Django password hashes start with algorithm prefix e.g., 'pbkdf2_sha256$', 'argon2$', 'bcrypt$'
            has_hash_prefix = any(
                self.password.startswith(prefix)
                for prefix in ("pbkdf2_sha256$", "argon2", "bcrypt", "scrypt", "crypt")
            )
            if not has_hash_prefix:
                self.password = make_password(self.password)

        super().save(*args, **kwargs)
