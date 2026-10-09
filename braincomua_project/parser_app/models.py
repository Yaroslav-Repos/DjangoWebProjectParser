from django.db import models

# Create your models here.
from django.db import models
from django.contrib.postgres.fields import ArrayField


class Product(models.Model):

    name = models.CharField(max_length=500, null=True)
    manufacturer = models.CharField(max_length=255, null=True)
    color = models.CharField(max_length=100, null=True)
    memory = models.CharField(max_length=100, null=True)
    product_code = models.CharField(max_length=100, null=True)

    price = models.CharField(max_length=100, null=True)
    sale_price = models.CharField(max_length=100, null=True)

    screen_diagonal = models.CharField(max_length=100, null=True)
    display_resolution = models.CharField(max_length=100, null=True)

    reviews_count = models.IntegerField(null=True)

    photos = ArrayField(models.URLField(max_length=1000, null=True), null=True, blank=True)

    characteristics = models.JSONField(null=True, blank=True)

    link = models.URLField(max_length=1000, null=True, blank=True, unique=True)

    status = models.CharField(max_length=50, default="New", null=True) 

    def __str__(self):
        return self.name