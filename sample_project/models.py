from django.db import models


class Author(models.Model):
    name = models.CharField(max_length=200)
    email = models.EmailField()

    def __str__(self):
        return self.name

    def full_profile(self):
        return f"{self.name} <{self.email}>"


class Book(models.Model):
    title = models.CharField(max_length=200)
    author = models.ForeignKey(Author, on_delete=models.CASCADE)
    published_year = models.IntegerField()

    def __str__(self):
        return self.title

    def is_recent(self):
        return self.published_year >= 2020


class Review(models.Model):
    book = models.ForeignKey(Book, on_delete=models.CASCADE)
    reviewer_name = models.CharField(max_length=200)
    rating = models.IntegerField()
    tags = models.ManyToManyField('Tag', blank=True)

    def summary(self):
        return f"{self.reviewer_name}: {self.rating}/5"


class Tag(models.Model):
    name = models.CharField(max_length=50)

    def __str__(self):
        return self.name


# Never referenced anywhere else in the project -> should be flagged dead
def unused_helper_in_models():
    return "nobody calls me"
